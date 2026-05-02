"""Bug bank — vulnerability templates indexed by class.

Each module in this package exports a module-level ``TEMPLATE`` constant
that satisfies the ``BugTemplate`` protocol. ``ALL_TEMPLATES`` aggregates
them for the bank loader.

Adding a new bug:
  1. Drop a module here that defines ``TEMPLATE = MyTemplate(...)``.
  2. Add the import and append to ``ALL_TEMPLATES`` below.
  3. Verify the template's ``verify()`` is *strict* — false positives reward
     lazy claims, false negatives erase real exploits.
"""

from hostile_mesh_combat.bugs import (
    auth_bypass_admin_header,
    auth_bypass_login_empty_password,
    broken_access_priv_export,
    cmd_injection_ping,
    idor_invoice_owner_skip,
    idor_user_lookup,
    path_traversal_secrets,
    race_condition_transfer,
    sig_replay_transfer,
    sqli_login_concat,
    sqli_user_search,
    cmd_injection_archive,
)

ALL_TEMPLATES = [
    auth_bypass_login_empty_password.TEMPLATE,
    auth_bypass_admin_header.TEMPLATE,
    idor_invoice_owner_skip.TEMPLATE,
    idor_user_lookup.TEMPLATE,
    sqli_login_concat.TEMPLATE,
    sqli_user_search.TEMPLATE,
    cmd_injection_ping.TEMPLATE,
    cmd_injection_archive.TEMPLATE,
    path_traversal_secrets.TEMPLATE,
    race_condition_transfer.TEMPLATE,
    broken_access_priv_export.TEMPLATE,
    sig_replay_transfer.TEMPLATE,
]

__all__ = ["ALL_TEMPLATES"]
