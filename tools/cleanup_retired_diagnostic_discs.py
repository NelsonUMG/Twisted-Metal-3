"""Retire superseded diagnostic disc outputs; preserve source patches and reports."""
import cleanup_obsolete_discs as cleanup

cleanup.OUT = cleanup.ROOT / 'docs/cleanup_diagnostic_discs_20261021'
cleanup.NAMES = (
    'diagnostics/constraints_constant_candidate_v1/TM3_CONSTRAINTS_CONSTANTS_V1',
    'diagnostics/timer_recovery_v1/TM3_TIMER_RECOVERY_V1',
    'diagnostics/link_pause_v1/game/TM3_LINK_PAUSE_V1',
    'diagnostics/menu_reload_v1/game/TM3_MENU_RELOAD_V1',
    'diagnostics/path_stamp_v1/game/TM3_PATH_STAMP_V1',
    'diagnostics/projectile_basis_v1/game/TM3_PROJECTILE_BASIS_V1',
    'diagnostics/sqrt_dispatch_v3/game/TM3_SQRT_DISPATCH_V3',
    'diagnostics/sqrt_fast_v2/game/TM3_SQRT_FAST_V2',
    'diagnostics/sqrt_pair_v1/game/TM3_SQRT_PAIR_V1',
    'diagnostics/target_lifetime_v1/game/TM3_TARGET_LIFETIME_V1',
)

if __name__ == '__main__':
    cleanup.main()
