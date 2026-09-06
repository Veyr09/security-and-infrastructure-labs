//! A streaming RFC 4180 CSV reader.
//!
//! Splitting on commas is the usual shortcut and it is wrong the moment a field
//! contains a comma, a quote, or a newline. Real exports contain all three, so
//! this reads the file as a byte stream and tracks quoting state, which also
//! means a record can span physical lines without the reader losing its place.
//!
//! Memory is bounded by the largest single record, not by the file.

use std::io::{self, Read};

const QUOTE: u8 = b'"';
const CR: u8 = b'\r';
const LF: u8 = b'\n';
const READ_BUFFER_BYTES: usize = 64 * 1024;

pub struct Reader<R: Read> {
    source: R,
    delimiter: u8,
    buffer: Vec<u8>,
    filled: usize,
    position: usize,
    exhausted: bool,
    /// Byte offset in the file where the current record started, for error messages.
    pub record_number: u64,
}

#[derive(Debug, PartialEq)]
pub struct Record {
    pub fields: Vec<String>,
    /// 1-based line the record started on, so a person can find it in an editor.
    pub line: u64,
}

impl<R: Read> Reader<R> {
    pub fn new(source: R, delimiter: u8) -> Self {
        Reader {
            source,
            delimiter,
            buffer: vec![0; READ_BUFFER_BYTES],
            filled: 0,
            position: 0,
            exhausted: false,
            record_number: 0,
        }
    }

    fn next_byte(&mut self) -> io::Result<Option<u8>> {
        if self.position == self.filled {
            if self.exhausted {
                return Ok(None);
            }
            self.filled = self.source.read(&mut self.buffer)?;
            self.position = 0;
            if self.filled == 0 {
                self.exhausted = true;
                return Ok(None);
            }
        }
        let byte = self.buffer[self.position];
        self.position += 1;
        Ok(Some(byte))
    }

    fn peek_byte(&mut self) -> io::Result<Option<u8>> {
        if self.position == self.filled {
            if self.exhausted {
                return Ok(None);
            }
            self.filled = self.source.read(&mut self.buffer)?;
            self.position = 0;
            if self.filled == 0 {
                self.exhausted = true;
                return Ok(None);
            }
        }
        Ok(Some(self.buffer[self.position]))
    }

    /// The next record, or None at end of input. Blank trailing lines are skipped.
    pub fn next_record(&mut self) -> io::Result<Option<Record>> {
        let mut fields: Vec<String> = Vec::new();
        let mut field = Vec::new();
        let mut in_quotes = false;
        let mut saw_any = false;
        let start_line = self.record_number + 1;

        loop {
            let byte = match self.next_byte()? {
                Some(b) => b,
                None => {
                    if !saw_any && fields.is_empty() && field.is_empty() {
                        return Ok(None);
                    }
                    fields.push(take_utf8(&mut field));
                    self.record_number += 1;
                    return Ok(Some(Record { fields, line: start_line }));
                }
            };
            saw_any = true;

            if in_quotes {
                if byte == QUOTE {
                    // A doubled quote inside a quoted field is a literal quote.
                    if self.peek_byte()? == Some(QUOTE) {
                        self.position += 1;
                        field.push(QUOTE);
                    } else {
                        in_quotes = false;
                    }
                } else {
                    field.push(byte);
                }
                continue;
            }

            if byte == QUOTE && field.is_empty() {
                in_quotes = true;
            } else if byte == self.delimiter {
                fields.push(take_utf8(&mut field));
            } else if byte == LF || byte == CR {
                if byte == CR && self.peek_byte()? == Some(LF) {
                    self.position += 1;
                }
                self.record_number += 1;
                // A completely blank line carries no record; skip it rather than
                // emitting a spurious one-empty-field row.
                if fields.is_empty() && field.is_empty() {
                    return self.next_record();
                }
                fields.push(take_utf8(&mut field));
                return Ok(Some(Record { fields, line: start_line }));
            } else {
                field.push(byte);
            }
        }
    }
}

/// Bytes to String, replacing invalid sequences rather than failing the run.
/// A single bad byte in a 10 GB export should not stop the job; it shows up in
/// the rejects file instead.
fn take_utf8(bytes: &mut Vec<u8>) -> String {
    let text = String::from_utf8_lossy(bytes).into_owned();
    bytes.clear();
    text
}

/// Write one record back out, quoting only where RFC 4180 requires it.
pub fn write_record(out: &mut impl io::Write, fields: &[String], delimiter: u8) -> io::Result<()> {
    for (index, field) in fields.iter().enumerate() {
        if index > 0 {
            out.write_all(&[delimiter])?;
        }
        let needs_quotes = field
            .bytes()
            .any(|b| b == QUOTE || b == delimiter || b == LF || b == CR);
        if needs_quotes {
            out.write_all(b"\"")?;
            for byte in field.bytes() {
                if byte == QUOTE {
                    out.write_all(b"\"\"")?;
                } else {
                    out.write_all(&[byte])?;
                }
            }
            out.write_all(b"\"")?;
        } else {
            out.write_all(field.as_bytes())?;
        }
    }
    out.write_all(b"\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn read_all(input: &str) -> Vec<Vec<String>> {
        let mut reader = Reader::new(input.as_bytes(), b',');
        let mut out = Vec::new();
        while let Some(record) = reader.next_record().unwrap() {
            out.push(record.fields);
        }
        out
    }

    #[test]
    fn plain_rows() {
        assert_eq!(read_all("a,b\n1,2\n"), vec![vec!["a", "b"], vec!["1", "2"]]);
    }

    #[test]
    fn quoted_field_with_delimiter() {
        assert_eq!(read_all("a,b\n\"x,y\",2\n"), vec![vec!["a", "b"], vec!["x,y", "2"]]);
    }

    #[test]
    fn escaped_quote_inside_quoted_field() {
        assert_eq!(read_all("a\n\"he said \"\"hi\"\"\"\n"), vec![vec!["a"], vec!["he said \"hi\""]]);
    }

    #[test]
    fn embedded_newline_keeps_one_record() {
        let rows = read_all("a,b\n\"line1\nline2\",2\n");
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[1], vec!["line1\nline2", "2"]);
    }

    #[test]
    fn crlf_and_final_row_without_newline() {
        assert_eq!(read_all("a,b\r\n1,2"), vec![vec!["a", "b"], vec!["1", "2"]]);
    }

    #[test]
    fn blank_lines_are_skipped() {
        assert_eq!(read_all("a\n\n1\n"), vec![vec!["a"], vec!["1"]]);
    }

    #[test]
    fn empty_fields_are_preserved() {
        assert_eq!(read_all("a,b,c\n1,,3\n"), vec![vec!["a", "b", "c"], vec!["1", "", "3"]]);
    }

    #[test]
    fn round_trip_quoting() {
        let mut out = Vec::new();
        let fields = vec!["plain".to_string(), "has,comma".to_string(), "has\"quote".to_string()];
        write_record(&mut out, &fields, b',').unwrap();
        assert_eq!(String::from_utf8(out.clone()).unwrap(), "plain,\"has,comma\",\"has\"\"quote\"\n");
        assert_eq!(read_all(&String::from_utf8(out).unwrap())[0], fields);
    }
}
