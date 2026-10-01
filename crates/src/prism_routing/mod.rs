// Marabbecca's multi-realization extensions to the vendored SABRE files in
// `crate::sabre`. The vendored files carry only the minimum in-place edits
// needed to support multi-realization 2Q nodes (an enum variant, type
// aliases, a handful of one-line dispatches); everything else lives here.

pub mod ext;
pub mod input;
pub mod layout;
pub mod routing;
