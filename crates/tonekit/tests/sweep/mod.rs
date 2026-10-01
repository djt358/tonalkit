//! What the substitution sweeps share: the readings, how tones are spoken (ruling R8), grading a
//! reading, and every single full-tone substitution of a spoken reading.

use tonekit::{
    assess, AccentId, Analysis, AssessRequest, Candidate, CandidateId, GradingTarget, LanguagePack,
    ToneId, ToneTarget,
};

const CMN_TOML: &str = include_str!("../../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../../packs/cmn/cmn.calib.json");

pub const RATE: u32 = 16_000;
const FULL_TONES: [&str; 4] = ["1", "2", "3", "4"];

/// Each full tone in each position, and no 3-3 pair (third-tone sandhi is not what this tests).
pub const READINGS: [[&str; 3]; 6] = [
    ["1", "2", "3"],
    ["2", "3", "4"],
    ["3", "4", "1"],
    ["4", "1", "2"],
    ["4", "1", "3"],
    ["2", "4", "1"],
];

/// The shipped cmn pack with its seed calibration.
pub fn cmn() -> LanguagePack {
    LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap()
}

/// Ruling R8: "1" → [5,5], "2" → [3,5], "3" → [2,1,4] when phrase-final and [2,1] otherwise,
/// "4" → [5,1].
pub fn knots(tone: &str, last: bool) -> Vec<f32> {
    match tone {
        "1" => vec![5.0, 5.0],
        "2" => vec![3.0, 5.0],
        "3" if last => vec![2.0, 1.0, 4.0],
        "3" => vec![2.0, 1.0],
        "4" => vec![5.0, 1.0],
        other => panic!("no spoken form for tone {other}"),
    }
}

/// `p_correct` of each syllable of `intended` on the analysed clip, graded alone (no distractors).
fn grade(a: &Analysis, pack: &LanguagePack, intended: &[&str]) -> Vec<f32> {
    let request = AssessRequest {
        grading: GradingTarget {
            accent: AccentId("cmn-standard".into()),
            style: None,
            style_weight: 0.0,
        },
        intended: Candidate {
            id: CandidateId("spell".into()),
            targets: intended
                .iter()
                .map(|t| ToneTarget {
                    tone: ToneId((*t).into()),
                    lexical_variants: Vec::new(),
                    label: None,
                })
                .collect(),
        },
        distractors: Vec::new(),
        external: Vec::new(),
        compare_accents: Vec::new(),
    };
    assess(a, pack, &request)
        .unwrap()
        .syllables
        .iter()
        .map(|s| s.p_correct)
        .collect()
}

/// One single substitution: the spoken reading, the reading graded, which syllable differs, and
/// that syllable's `p_correct` under the wrong reading and under the spoken one.
pub struct Substitution {
    spoken: String,
    intended: String,
    position: usize,
    p_wrong: f32,
    p_correct: f32,
}

impl Substitution {
    /// The wrong tone reached 0.5 or the spoken tone's own grade.
    pub fn graded_too_well(&self) -> bool {
        self.p_wrong >= 0.5 || self.ranked_wrong()
    }

    /// The wrong tone reached the spoken tone's own grade.
    pub fn ranked_wrong(&self) -> bool {
        self.p_wrong >= self.p_correct
    }

    pub fn describe(&self) -> String {
        format!(
            "spoken {} graded as {}: syllable {} p {:.3} (spoken tone {:.3})",
            self.spoken, self.intended, self.position, self.p_wrong, self.p_correct
        )
    }
}

/// Every single full-tone substitution of `spoken`, graded on its analysis `a`.
pub fn substitutions(a: &Analysis, pack: &LanguagePack, spoken: [&str; 3]) -> Vec<Substitution> {
    let right = grade(a, pack, &spoken);
    let mut out = Vec::new();
    for position in 0..spoken.len() {
        for wrong in FULL_TONES.iter().filter(|&&t| t != spoken[position]) {
            let mut intended = spoken;
            intended[position] = wrong;
            out.push(Substitution {
                spoken: spoken.join("-"),
                intended: intended.join("-"),
                position,
                p_wrong: grade(a, pack, &intended)[position],
                p_correct: right[position],
            });
        }
    }
    out
}

/// Prints how many of `subs` graded too well, which, and the best-graded wrong tone; returns the
/// count.
pub fn report<'a>(label: &str, subs: impl IntoIterator<Item = &'a Substitution>) -> usize {
    let subs: Vec<&Substitution> = subs.into_iter().collect();
    let misses: Vec<&Substitution> = subs
        .iter()
        .copied()
        .filter(|s| s.graded_too_well())
        .collect();
    eprintln!(
        "{label}: {} of {} substitutions graded too well",
        misses.len(),
        subs.len()
    );
    for m in &misses {
        eprintln!("  {}", m.describe());
    }
    if let Some(worst) = subs.iter().max_by(|a, b| a.p_wrong.total_cmp(&b.p_wrong)) {
        eprintln!("  highest wrong: {}", worst.describe());
    }
    misses.len()
}
