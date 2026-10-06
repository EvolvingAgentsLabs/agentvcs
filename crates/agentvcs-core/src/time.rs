//! RFC 3339 UTC timestamps without a date-time dependency.

use std::time::{SystemTime, UNIX_EPOCH};

/// Civil date from days since 1970-01-01 (H. Hinnant's algorithm).
fn civil(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// `YYYY-MM-DDTHH:MM:SS.mmmZ` for a Unix time in milliseconds.
pub fn rfc3339_ms(ms: i64) -> String {
    let secs = ms.div_euclid(1000);
    let (y, mo, d) = civil(secs.div_euclid(86_400));
    let t = secs.rem_euclid(86_400);
    format!(
        "{y:04}-{mo:02}-{d:02}T{:02}:{:02}:{:02}.{:03}Z",
        t / 3600,
        (t / 60) % 60,
        t % 60,
        ms.rem_euclid(1000)
    )
}

/// Now, as RFC 3339 UTC with milliseconds.
pub fn now() -> String {
    let ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as i64);
    rfc3339_ms(ms)
}

#[cfg(test)]
mod tests {
    #[test]
    fn known_instants() {
        assert_eq!(super::rfc3339_ms(0), "1970-01-01T00:00:00.000Z");
        assert_eq!(
            super::rfc3339_ms(1_791_288_000_123),
            "2026-10-06T12:00:00.123Z"
        );
        assert_eq!(
            super::rfc3339_ms(951_782_400_000),
            "2000-02-29T00:00:00.000Z"
        );
    }
}
