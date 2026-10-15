//! Named speaker registers for sweeps.

use tonekit_core::Register;

use crate::pitch::register_for;

/// A synthetic speaker: the pitch of Chao 1 and Chao 5.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Speaker {
    pub name: &'static str,
    pub floor_hz: f32,
    pub ceil_hz: f32,
}

impl Speaker {
    /// The speaker's register, already warm ([`register_for`]).
    pub fn register(&self) -> Register {
        register_for(self.floor_hz, self.ceil_hz)
    }
}

/// A low male voice, 85 to 160 Hz.
pub const MALE_LOW: Speaker = Speaker {
    name: "male-low",
    floor_hz: 85.0,
    ceil_hz: 160.0,
};

/// A register spanning exactly an octave, 100 to 200 Hz: a falling tone into a high level one
/// (T4 → T1) crosses a full octave, where pYIN can lock onto the subharmonic.
pub const OCTAVE_SPANNING: Speaker = Speaker {
    name: "octave-spanning",
    floor_hz: 100.0,
    ceil_hz: 200.0,
};

/// A female voice, 180 to 330 Hz.
pub const FEMALE: Speaker = Speaker {
    name: "female",
    floor_hz: 180.0,
    ceil_hz: 330.0,
};

/// A wide, expressive register, 110 to 260 Hz (more than an octave).
pub const WIDE: Speaker = Speaker {
    name: "wide",
    floor_hz: 110.0,
    ceil_hz: 260.0,
};

/// The speakers of the fluent-speech sweep.
pub const FLUENT_SPEAKERS: [Speaker; 4] = [MALE_LOW, OCTAVE_SPANNING, FEMALE, WIDE];
