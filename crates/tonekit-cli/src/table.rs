//! Plain-text tables for the terminal.

use tonekit::{
    DeltaKind, MeasureIssue, Measured, ShapeDelta, ToneLattice, UtteranceAssessment, HOP,
    SAMPLE_RATE,
};

/// Placeholder for a value that is absent.
const NONE: &str = "-";

/// One row per syllable (`labels[i]` names syllable `i`, else `s{i+1}`), then any measurement
/// caveats, then a last line with the overall score, margin and rank.
pub fn assessment(a: &UtteranceAssessment, labels: &[Option<String>]) -> String {
    let name = |i: usize| {
        labels
            .get(i)
            .cloned()
            .flatten()
            .unwrap_or_else(|| format!("s{}", i + 1))
    };
    let mut rows = vec![row([
        "label",
        "expected",
        "heard",
        "p_correct",
        "distance",
        "component",
        "deltas",
    ])];
    for (i, s) in a.syllables.iter().enumerate() {
        rows.push(vec![
            name(i),
            s.expected.0.clone(),
            s.heard.as_ref().map_or(NONE.into(), |t| t.0.clone()),
            format!("{:.2}", s.p_correct),
            s.distance.map_or(NONE.into(), |d| format!("{d:.2}")),
            s.component.clone().unwrap_or_else(|| NONE.into()),
            deltas(&s.deltas),
        ]);
    }
    let mut out = render(&rows);
    for (i, s) in a.syllables.iter().enumerate() {
        if let Some(caveat) = caveat(&s.measured) {
            out.push_str(&format!("{}: {caveat}\n", name(i)));
        }
    }
    let overall = a
        .overall
        .map_or("not checked".to_owned(), |o| format!("{o:.2}"));
    out.push_str(&format!(
        "overall {overall}  margin {:.2}  rank {}\n",
        a.margin_llr, a.intended_rank
    ));
    out
}

/// One row per tone-bearing unit: its span, the most probable tone and every tone's posterior.
pub fn lattice(l: &ToneLattice) -> String {
    let mut header = vec!["tbu".to_owned(), "span_ms".to_owned(), "best".to_owned()];
    header.extend(l.inventory.iter().map(|t| format!("p({})", t.0)));
    header.push("measured".to_owned());
    let mut rows = vec![header];
    for (i, tbu) in l.tbus.iter().enumerate() {
        let best = match tbu.measured {
            Measured::NotMeasured { .. } => None,
            _ => most_probable(&tbu.posterior).and_then(|k| l.inventory.get(k)),
        };
        let mut cells = vec![
            (i + 1).to_string(),
            format!("{}-{}", ms(tbu.span.start_frame), ms(tbu.span.end_frame)),
            best.map_or(NONE.into(), |t| t.0.clone()),
        ];
        cells.extend(tbu.posterior.iter().map(|p| format!("{p:.2}")));
        cells.push(measured(&tbu.measured));
        rows.push(cells);
    }
    let mut out = render(&rows);
    if l.tbus.is_empty() {
        out.push_str("no syllable nuclei found\n");
    }
    out
}

fn row<const N: usize>(cells: [&str; N]) -> Vec<String> {
    cells.iter().map(|c| (*c).to_owned()).collect()
}

/// Left-aligned columns two spaces apart; the last column is not padded.
fn render(rows: &[Vec<String>]) -> String {
    let columns = rows.iter().map(Vec::len).max().unwrap_or(0);
    let widths: Vec<usize> = (0..columns)
        .map(|c| {
            rows.iter()
                .filter_map(|r| r.get(c))
                .map(|cell| cell.chars().count())
                .max()
                .unwrap_or(0)
        })
        .collect();
    let mut out = String::new();
    for r in rows {
        let last = r.len().saturating_sub(1);
        for (c, cell) in r.iter().enumerate() {
            out.push_str(cell);
            if c < last {
                let pad = widths[c] - cell.chars().count() + 2;
                out.push_str(&" ".repeat(pad));
            }
        }
        out.push('\n');
    }
    out
}

fn deltas(deltas: &[ShapeDelta]) -> String {
    if deltas.is_empty() {
        return NONE.to_owned();
    }
    deltas
        .iter()
        .map(|d| match d.kind {
            DeltaKind::TurnEarlier => format!("turn earlier {:.0}ms", d.amount),
            DeltaKind::TurnLater => format!("turn later {:.0}ms", d.amount),
            DeltaKind::StartHigher => format!("start higher {:.1}", d.amount),
            DeltaKind::StartLower => format!("start lower {:.1}", d.amount),
            DeltaKind::EndHigher => format!("end higher {:.1}", d.amount),
            DeltaKind::EndLower => format!("end lower {:.1}", d.amount),
            DeltaKind::WiderRange => format!("wider range {:.1}", d.amount),
            DeltaKind::NarrowerRange => format!("narrower range {:.1}", d.amount),
        })
        .collect::<Vec<_>>()
        .join(", ")
}

/// Why a syllable's numbers deserve a second look, if they do. The CLI always analyses from a
/// cold-start register, so `ColdStartRegister` alone is the norm and not worth a line.
fn caveat(m: &Measured) -> Option<String> {
    match m {
        Measured::Full => None,
        Measured::NotMeasured { issue } => Some(format!("not measured ({issue:?})")),
        Measured::Partial { issues } => {
            let notable: Vec<String> = issues
                .iter()
                .filter(|i| **i != MeasureIssue::ColdStartRegister)
                .map(|i| format!("{i:?}"))
                .collect();
            (!notable.is_empty()).then(|| format!("partial ({})", notable.join(", ")))
        }
    }
}

fn measured(m: &Measured) -> String {
    match m {
        Measured::Full => "full".to_owned(),
        Measured::Partial { issues } => {
            let issues: Vec<String> = issues.iter().map(|i| format!("{i:?}")).collect();
            format!("partial ({})", issues.join(", "))
        }
        Measured::NotMeasured { issue } => format!("not measured ({issue:?})"),
    }
}

/// Index of the largest posterior (the first of equals).
fn most_probable(posterior: &[f32]) -> Option<usize> {
    posterior
        .iter()
        .enumerate()
        .fold(None, |best: Option<(usize, f32)>, (k, &p)| match best {
            Some((_, top)) if top >= p => best,
            _ => Some((k, p)),
        })
        .map(|(k, _)| k)
}

/// The start of frame `frame` in milliseconds (frame `i` is centred at `i * HOP` samples).
fn ms(frame: u32) -> u64 {
    u64::from(frame) * HOP as u64 * 1000 / u64::from(SAMPLE_RATE)
}
