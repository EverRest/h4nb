"""Names, types and help texts of the metrics (specs/002-run-metrics/contracts/metrics.md)."""

GAUGE, COUNTER = "gauge", "counter"

# name -> (type, help). A counter name has no `_total` suffix here. The client library adds it.
METRICS = {
    "h4nb_run_info": (GAUGE, "Run record from run_info.txt and config.used. The value is 1."),
    "h4nb_run_state": (GAUGE, "Run state: 0 running, 1 finished, 2 stopped early, 3 stalled."),
    "h4nb_sim_time": (GAUGE, "Simulation time of the last line of energy.dat."),
    "h4nb_t_end": (GAUGE, "End time of the run (key t_end)."),
    "h4nb_progress_ratio": (GAUGE, "Simulation time divided by t_end."),
    "h4nb_wall_seconds": (COUNTER, "Sum of wall_s of performance.dat, in seconds."),
    "h4nb_eta_seconds": (GAUGE, "Estimated wall time to t_end, from the last 10 diag segments, in seconds."),
    "h4nb_last_update_age_seconds": (GAUGE, "Seconds since the newest change of a .dat file of the run."),
    "h4nb_run_start_timestamp_seconds": (GAUGE, "Start of the run (start_utc of run_info.txt), Unix time."),
    "h4nb_run_end_timestamp_seconds": (GAUGE, "Time of the last line of energy.dat, Unix time."),
    "h4nb_particles": (GAUGE, "Number of bodies N, the central body included."),
    "h4nb_config_value": (GAUGE, "Numeric value of a key of config.used."),
    "h4nb_energy_rel_err": (GAUGE, "Relative energy error abs(E - E0 - W_diss) / D (energy.dat rel_err)."),
    "h4nb_energy_max_rel_err": (GAUGE, "Largest relative energy error since t = 0."),
    "h4nb_energy_mean_rel_err": (GAUGE, "Mean relative energy error since t = 0."),
    "h4nb_energy_total": (GAUGE, "Total energy E."),
    "h4nb_dissipated_work": (GAUGE, "Work of the dissipative force since t = 0 (W_diss)."),
    "h4nb_momentum_rel_change": (GAUGE, "Relative change of the total momentum (dP_rel)."),
    "h4nb_angular_momentum_rel_change": (GAUGE, "Relative change of the total angular momentum (dL_rel)."),
    "h4nb_period_max_rel_err": (GAUGE, "Largest relative energy error in one reference period (energy_periods.dat)."),
    "h4nb_dt_min": (GAUGE, "Smallest individual time step."),
    "h4nb_dt_mean": (GAUGE, "Mean individual time step."),
    "h4nb_dt_max": (GAUGE, "Largest individual time step in use."),
    "h4nb_active_per_block_step": (GAUGE, "Mean number of active particles in one block step."),
    "h4nb_r_min": (GAUGE, "Smallest pair distance in the last diag segment."),
    "h4nb_block_steps": (COUNTER, "Sum of block steps (performance.dat block_steps)."),
    "h4nb_active_updates": (COUNTER, "Sum of particle updates (performance.dat active)."),
    "h4nb_pairs_per_second": (GAUGE, "Force pair evaluations per second in the last diag segment."),
    "h4nb_gflops": (GAUGE, "60 x pairs_per_s / 1e9 (60 FP64 operations for each pair)."),
    "h4nb_particle_updates_per_second": (GAUGE, "Particle updates per second in the last diag segment."),
    "h4nb_segment_wall_seconds": (GAUGE, "Wall time of the last diag segment, in seconds."),
}

EXPORTER_METRICS = {
    "h4nb_exporter_runs": (GAUGE, "Number of runs found."),
    "h4nb_exporter_read_errors": (COUNTER, "Files that could not be read and lines that could not be parsed."),
    "h4nb_exporter_scrape_seconds": (GAUGE, "Time of the last collection, in seconds."),
}
