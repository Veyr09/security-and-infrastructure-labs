//! csvguard - validate a CSV against column rules, in one streaming pass.
//!
//! Splits an input file into rows that satisfy every rule and rows that do not,
//! and explains each rejection by row, column and reason. Memory use is bounded
//! by the widest single record rather than by the size of the file, so a 50 GB
//! export costs the same resident memory as a 50 KB one.
//!
//! Usage:
//!   csvguard --input orders.csv --clean clean.csv --rejects rejects.csv \
//!            --rule order_id:req --rule qty:int --rule price:dec \
//!            --rule ordered_on:date --rule status:enum:new|paid|void \
//!            --rule notes:max:200
//!
//! Reads stdin when --input is omitted. --summary-json prints the counts as JSON
//! on stderr so a scheduler can act on them.

mod csv;
mod rules;

use rules::Rule;
use std::collections::BTreeMap;
use std::fs::File;
use std::io::{self, BufWriter, Read, Write};
use std::process::ExitCode;

const EXIT_BAD_USAGE: u8 = 2;
const EXIT_IO_ERROR: u8 = 3;

struct Options {
    input: Option<String>,
    clean: Option<String>,
    rejects: Option<String>,
    delimiter: u8,
    summary_json: bool,
    rules: Vec<(String, Rule)>,
}

fn parse_arguments(arguments: Vec<String>) -> Result<Options, String> {
    let mut options = Options {
        input: None,
        clean: None,
        rejects: None,
        delimiter: b',',
        summary_json: false,
        rules: Vec::new(),
    };
    let mut iterator = arguments.into_iter();
    while let Some(argument) = iterator.next() {
        let mut value = || {
            iterator
                .next()
                .ok_or_else(|| format!("{argument} needs a value"))
        };
        match argument.as_str() {
            "--input" => options.input = Some(value()?),
            "--clean" => options.clean = Some(value()?),
            "--rejects" => options.rejects = Some(value()?),
            "--summary-json" => options.summary_json = true,
            "--delimiter" => {
                let text = value()?;
                let bytes = text.as_bytes();
                if bytes.len() != 1 {
                    return Err(format!("--delimiter takes one character, got {text:?}"));
                }
                options.delimiter = bytes[0];
            }
            "--rule" => {
                let spec = value()?;
                let (column, rule_spec) = spec
                    .split_once(':')
                    .ok_or_else(|| format!("--rule wants column:rule, got {spec:?}"))?;
                let rule = Rule::parse(rule_spec)?;
                options.rules.push((column.to_string(), rule));
            }
            "--help" | "-h" => return Err("help".to_string()),
            other => return Err(format!("unknown argument {other:?}")),
        }
    }
    if options.rules.is_empty() {
        return Err("at least one --rule is required".to_string());
    }
    Ok(options)
}

struct Summary {
    rows_read: u64,
    rows_clean: u64,
    rows_rejected: u64,
    failures_by_column: BTreeMap<String, u64>,
}

fn run(options: Options) -> io::Result<Summary> {
    let source: Box<dyn Read> = match &options.input {
        Some(path) => Box::new(File::open(path)?),
        None => Box::new(io::stdin()),
    };
    let mut reader = csv::Reader::new(source, options.delimiter);

    let header = match reader.next_record()? {
        Some(record) => record.fields,
        None => {
            return Ok(Summary {
                rows_read: 0,
                rows_clean: 0,
                rows_rejected: 0,
                failures_by_column: BTreeMap::new(),
            })
        }
    };

    // Resolve rules to column positions once, so the hot loop is index lookups.
    let mut checks: Vec<(usize, String, Rule)> = Vec::new();
    for (column, rule) in &options.rules {
        match header.iter().position(|name| name.trim() == column) {
            Some(index) => checks.push((index, column.clone(), rule.clone())),
            None => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!(
                        "column {column:?} is not in the header: {}",
                        header.join(", ")
                    ),
                ))
            }
        }
    }

    let mut clean_out: Box<dyn Write> = match &options.clean {
        Some(path) => Box::new(BufWriter::new(File::create(path)?)),
        None => Box::new(io::sink()),
    };
    let mut reject_out: Box<dyn Write> = match &options.rejects {
        Some(path) => Box::new(BufWriter::new(File::create(path)?)),
        None => Box::new(io::sink()),
    };

    csv::write_record(&mut clean_out, &header, options.delimiter)?;
    csv::write_record(
        &mut reject_out,
        &["line".to_string(), "column".to_string(), "value".to_string(), "reason".to_string()],
        options.delimiter,
    )?;

    let mut summary = Summary {
        rows_read: 0,
        rows_clean: 0,
        rows_rejected: 0,
        failures_by_column: BTreeMap::new(),
    };

    while let Some(record) = reader.next_record()? {
        summary.rows_read += 1;
        let mut problems: Vec<(String, String, String)> = Vec::new();

        for (index, column, rule) in &checks {
            // A short row is a problem in itself: report it against the column
            // rather than silently treating the value as empty.
            let value = match record.fields.get(*index) {
                Some(value) => value.as_str(),
                None => {
                    problems.push((
                        column.clone(),
                        String::new(),
                        format!("row has {} fields, expected at least {}", record.fields.len(), index + 1),
                    ));
                    continue;
                }
            };
            if let Err(error) = rule.check(value) {
                problems.push((column.clone(), value.to_string(), error.reason));
            }
        }

        if problems.is_empty() {
            summary.rows_clean += 1;
            csv::write_record(&mut clean_out, &record.fields, options.delimiter)?;
        } else {
            summary.rows_rejected += 1;
            for (column, value, reason) in problems {
                *summary.failures_by_column.entry(column.clone()).or_insert(0) += 1;
                csv::write_record(
                    &mut reject_out,
                    &[record.line.to_string(), column, value, reason],
                    options.delimiter,
                )?;
            }
        }
    }

    clean_out.flush()?;
    reject_out.flush()?;
    Ok(summary)
}

fn report(summary: &Summary, as_json: bool) {
    let mut error = io::stderr();
    if as_json {
        let columns: Vec<String> = summary
            .failures_by_column
            .iter()
            .map(|(column, count)| format!("\"{column}\":{count}"))
            .collect();
        let _ = writeln!(
            error,
            "{{\"rows_read\":{},\"rows_clean\":{},\"rows_rejected\":{},\"failures_by_column\":{{{}}}}}",
            summary.rows_read,
            summary.rows_clean,
            summary.rows_rejected,
            columns.join(",")
        );
        return;
    }
    let _ = writeln!(error, "rows read      {}", summary.rows_read);
    let _ = writeln!(error, "rows clean     {}", summary.rows_clean);
    let _ = writeln!(error, "rows rejected  {}", summary.rows_rejected);
    if !summary.failures_by_column.is_empty() {
        let _ = writeln!(error, "failures by column:");
        for (column, count) in &summary.failures_by_column {
            let _ = writeln!(error, "  {column:<20} {count}");
        }
    }
}

fn main() -> ExitCode {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let options = match parse_arguments(arguments) {
        Ok(options) => options,
        Err(message) => {
            if message == "help" {
                eprintln!("{}", env!("CARGO_PKG_NAME"));
                eprintln!("{}", USAGE);
                return ExitCode::SUCCESS;
            }
            eprintln!("csvguard: {message}\n{USAGE}");
            return ExitCode::from(EXIT_BAD_USAGE);
        }
    };
    let summary_json = options.summary_json;
    match run(options) {
        Ok(summary) => {
            report(&summary, summary_json);
            // Non-zero when anything was rejected, so a cron job or CI step
            // fails loudly instead of quietly writing a short file.
            if summary.rows_rejected > 0 {
                ExitCode::FAILURE
            } else {
                ExitCode::SUCCESS
            }
        }
        Err(error) => {
            eprintln!("csvguard: {error}");
            ExitCode::from(EXIT_IO_ERROR)
        }
    }
}

const USAGE: &str = "\
usage: csvguard --rule COLUMN:RULE [--rule ...] [options]

rules:
  req              non-empty
  int              whole number
  dec              number
  date             YYYY-MM-DD, and the day must exist
  enum:a|b|c       one of these exact values
  max:N            at most N characters

options:
  --input PATH     read this file instead of stdin
  --clean PATH     write rows that passed
  --rejects PATH   write line, column, value, reason for each failure
  --delimiter C    field separator, default ,
  --summary-json   print the summary as JSON on stderr

exit: 0 all rows clean, 1 some rejected, 2 bad usage, 3 I/O error";
