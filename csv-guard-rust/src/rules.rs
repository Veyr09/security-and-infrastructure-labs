//! Column rules, and the reason a value failed one.
//!
//! Every rejection carries a reason a non-programmer can read, because the
//! rejects file is the part the client actually opens.

const MIN_YEAR: i64 = 1000;
const MAX_YEAR: i64 = 9999;

#[derive(Debug, Clone, PartialEq)]
pub enum Rule {
    Required,
    Integer,
    Decimal,
    Date,
    OneOf(Vec<String>),
    MaxLength(usize),
}

#[derive(Debug, PartialEq)]
pub struct RuleError {
    pub reason: String,
}

impl Rule {
    /// Parse `int`, `req`, `dec`, `date`, `enum:a|b|c`, `max:40`.
    pub fn parse(spec: &str) -> Result<Rule, String> {
        let (name, argument) = match spec.split_once(':') {
            Some((name, argument)) => (name, Some(argument)),
            None => (spec, None),
        };
        match (name, argument) {
            ("req", None) => Ok(Rule::Required),
            ("int", None) => Ok(Rule::Integer),
            ("dec", None) => Ok(Rule::Decimal),
            ("date", None) => Ok(Rule::Date),
            ("enum", Some(values)) if !values.is_empty() => {
                Ok(Rule::OneOf(values.split('|').map(str::to_string).collect()))
            }
            ("max", Some(number)) => number
                .parse::<usize>()
                .map(Rule::MaxLength)
                .map_err(|_| format!("max needs a whole number, got {number:?}")),
            _ => Err(format!(
                "unknown rule {spec:?}; expected req, int, dec, date, enum:a|b|c or max:N"
            )),
        }
    }

    /// An empty value passes everything except `req`. Emptiness is a separate
    /// question from wellformedness, and conflating the two is how "optional"
    /// columns end up rejected wholesale.
    pub fn check(&self, value: &str) -> Result<(), RuleError> {
        let trimmed = value.trim();
        if trimmed.is_empty() && !matches!(self, Rule::Required) {
            return Ok(());
        }
        let fail = |reason: String| Err(RuleError { reason });

        match self {
            Rule::Required => {
                if trimmed.is_empty() {
                    fail("required but empty".to_string())
                } else {
                    Ok(())
                }
            }
            Rule::Integer => match trimmed.parse::<i64>() {
                Ok(_) => Ok(()),
                Err(_) => fail(format!("not a whole number: {trimmed:?}")),
            },
            Rule::Decimal => match trimmed.parse::<f64>() {
                Ok(number) if number.is_finite() => Ok(()),
                _ => fail(format!("not a number: {trimmed:?}")),
            },
            Rule::Date => match parse_iso_date(trimmed) {
                Ok(()) => Ok(()),
                Err(reason) => fail(reason),
            },
            Rule::OneOf(allowed) => {
                if allowed.iter().any(|candidate| candidate == trimmed) {
                    Ok(())
                } else {
                    fail(format!("{trimmed:?} is not one of {}", allowed.join(", ")))
                }
            }
            Rule::MaxLength(limit) => {
                let length = trimmed.chars().count();
                if length <= *limit {
                    Ok(())
                } else {
                    fail(format!("{length} characters, limit is {limit}"))
                }
            }
        }
    }
}

/// YYYY-MM-DD, and the day has to exist. "2025-02-30" is the kind of value that
/// survives a regex and then breaks a database insert three steps later.
fn parse_iso_date(value: &str) -> Result<(), String> {
    let parts: Vec<&str> = value.split('-').collect();
    if parts.len() != 3 || parts[0].len() != 4 || parts[1].len() != 2 || parts[2].len() != 2 {
        return Err(format!("not YYYY-MM-DD: {value:?}"));
    }
    let numbers: Result<Vec<i64>, _> = parts.iter().map(|part| part.parse::<i64>()).collect();
    let numbers = numbers.map_err(|_| format!("not YYYY-MM-DD: {value:?}"))?;
    let (year, month, day) = (numbers[0], numbers[1], numbers[2]);

    if !(MIN_YEAR..=MAX_YEAR).contains(&year) {
        return Err(format!("year out of range: {value:?}"));
    }
    if !(1..=12).contains(&month) {
        return Err(format!("month {month} does not exist: {value:?}"));
    }
    if day < 1 || day > days_in_month(year, month) {
        return Err(format!("day {day} does not exist in that month: {value:?}"));
    }
    Ok(())
}

fn days_in_month(year: i64, month: i64) -> i64 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if is_leap_year(year) => 29,
        2 => 28,
        _ => 0,
    }
}

fn is_leap_year(year: i64) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn passes(rule: &Rule, value: &str) -> bool {
        rule.check(value).is_ok()
    }

    #[test]
    fn required_rejects_empty_and_whitespace() {
        assert!(!passes(&Rule::Required, ""));
        assert!(!passes(&Rule::Required, "   "));
        assert!(passes(&Rule::Required, "x"));
    }

    #[test]
    fn optional_columns_allow_empty() {
        assert!(passes(&Rule::Integer, ""));
        assert!(passes(&Rule::Date, "  "));
    }

    #[test]
    fn integers() {
        assert!(passes(&Rule::Integer, "42"));
        assert!(passes(&Rule::Integer, "-7"));
        assert!(!passes(&Rule::Integer, "4.2"));
        assert!(!passes(&Rule::Integer, "1,000"));
    }

    #[test]
    fn decimals_reject_infinity_and_text() {
        assert!(passes(&Rule::Decimal, "3.14"));
        assert!(passes(&Rule::Decimal, "-0.5"));
        assert!(!passes(&Rule::Decimal, "inf"));
        assert!(!passes(&Rule::Decimal, "$12.00"));
    }

    #[test]
    fn dates_must_be_real_days() {
        assert!(!passes(&Rule::Date, "2026-02-29"));  // 2026 is not a leap year
        assert!(!passes(&Rule::Date, "2025-02-30"));
        assert!(!passes(&Rule::Date, "2025-13-01"));
        assert!(!passes(&Rule::Date, "01/02/2025"));
    }

    #[test]
    fn leap_years() {
        assert!(passes(&Rule::Date, "2024-02-29"));
        assert!(!passes(&Rule::Date, "2023-02-29"));
        assert!(passes(&Rule::Date, "2000-02-29"));
        assert!(!passes(&Rule::Date, "1900-02-29"));
    }

    #[test]
    fn enum_and_max_length() {
        let status = Rule::parse("enum:new|paid|void").unwrap();
        assert!(passes(&status, "paid"));
        assert!(!passes(&status, "PAID"));
        let short = Rule::parse("max:3").unwrap();
        assert!(passes(&short, "abc"));
        assert!(!passes(&short, "abcd"));
    }

    #[test]
    fn max_length_counts_characters_not_bytes() {
        let short = Rule::parse("max:3").unwrap();
        assert!(passes(&short, "łód"));
    }

    #[test]
    fn bad_specs_are_rejected_with_a_useful_message() {
        assert!(Rule::parse("nope").is_err());
        assert!(Rule::parse("max:abc").is_err());
        assert!(Rule::parse("enum:").is_err());
    }

    #[test]
    fn reasons_name_the_value() {
        let error = Rule::Integer.check("abc").unwrap_err();
        assert!(error.reason.contains("abc"), "reason was {:?}", error.reason);
    }
}
