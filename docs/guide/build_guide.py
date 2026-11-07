#!/usr/bin/env python3
"""Builds the h4nb guide: docs/guide/h4nb-guide.<lang>.html and .pdf for en, it, uk.

Usage: python3 docs/guide/build_guide.py [--no-pdf]
The PDF step needs Playwright with Chromium (python -m playwright, or node). It is optional.
Sources: README.md, specs/001-hermite-nbody-lib/{spec,quickstart,plan}.md, contracts/run-config.md.
Edit the text here, then run the script again. Do not edit the generated files by hand.
"""
import html, pathlib, subprocess, sys, json

HERE = pathlib.Path(__file__).resolve().parent
REPO = "https://github.com/EverRest/h4nb/blob/main/"
LANGS = ["en", "it", "uk"]
LANG_NAMES = {"en": "English", "it": "Italiano", "uk": "Українська"}

def code(s):
    return f"<pre><code>{html.escape(s.strip())}</code></pre>"

def table(head, rows):
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"

def k(s):
    return f"<code>{html.escape(s)}</code>"

# ---------------------------------------------------------------- shared code blocks
BUILD = """
make build                                   # Release, CMAKE_CUDA_ARCHITECTURES=native
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=89      # RTX 4070 Ti
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=90      # GH200 / H100
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES="89;90" # both
cmake --build build -j
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=90 -DH4NB_MPI=ON   # MPI (several nodes)
"""
RUN = """
build/h4nb_mkdisk n=127999 frac=0.1 out=disk128k.snap     # prints mean / median / mass-weighted period
build/h4nb_run ic=disk128k.snap out=run128k t_end=6.3125 diag=0.0625 eta=0.0005 devices=0,1
build/h4nb_order e=0.5                                     # Kepler orbit + 4th-order check
build/h4nb_bench sizes=16384,131072,1024000 tiles=64,128,256 bpsm=2,4,8 devices=0,1   # bench/bench.dat
build/h4nb_study ic=disk128k.snap out=study diag=0.0625 etas=0.001,0.0005,0.00025 devices=0,1   # eta study
tools/h4nb_pack.sh run128k study                            # pack logs + results -> h4nb_logs_<host>_<time>.tar.gz
"""
CFG = """
# configs/agn.cfg
preset=agn                    # eps = 0.01
eta=0.0005                    # measured value for 1e-8
dt_max=0.015625
diag=0.0625
period=6.283185307179586      # 2*pi for G = 1, M = 1, a = 1
"""
RUN_CFG = """
build/h4nb_run config=configs/agn.cfg ic=disk128k.snap out=run1 t_end=6.3125 devices=0,1
H4NB_ETA=0.00025 build/h4nb_run config=configs/agn.cfg ic=disk128k.snap out=run2 t_end=6.3125
build/h4nb_run config=run1/config.used out=run1_repeat     # repeat a run exactly
"""
MPI = """
# build with -DH4NB_MPI=ON; one rank per GPU; only rank 0 writes files
srun --ntasks-per-node=4 --gpus-per-task=1 --gpu-bind=single:1 \\
  build/h4nb_run config=configs/gh200.cfg ic=disk1m.snap out=run1m t_end=6.3125
mpirun -np 8 --map-by ppr:4:node --bind-to core \\
  build/h4nb_run config=configs/gh200.cfg ic=disk1m.snap out=run1m t_end=6.3125
mpirun -np 2 build/h4nb_run ic=disk.snap out=r2 t_end=6.3125 mpi_host_staging=1   # MPI not CUDA-aware
mpirun -np 4 build/h4nb_run ic=disk.snap out=r4 t_end=6.3125 device_offset=4      # GPUs 4-7 of a node
# exit codes on all ranks: 1 runtime, 2 settings/input, 3 NaN; CUDA/MPI error: MPI_Abort
"""
CPP = """
#include <cmath>
#include <h4nb/h4nb.hpp>

h4nb::Particles p = h4nb::read_snapshot("disk128k.snap");   // or h4nb::load_text("ic.txt")
h4nb::Config c;
c.eta = 5e-4;  c.dt_max = 1.0 / 64;  c.eps2 = 0.01 * 0.01;  c.devices = {0, 1};
h4nb::Simulation sim(p, c);
const auto e0 = sim.diagnostics();
sim.advance_to(6.3125);                                      // a multiple of dt_max
const auto e1 = sim.diagnostics();
double rel = std::abs((e1.E - e0.E) / e0.E);                 // the 1e-8 goal
if (sim.status() & h4nb::kNaN) { /* stop */ }
"""

AVAIL_KEYS = ["ic", "out", "t_end", "eta", "eta_init", "dt_max", "max_level", "eps", "mode", "fixed_level",
              "fixed_center", "devices", "diag", "snap", "r_close",
              "n", "central_id", "period", "period_kind", "preset", "G", "dissipation", "drag_tau", "drag_vbg", "tile", "blocks_per_sm",
              "snap_times", "energy_tol", "perf", "device_offset", "mpi_host_staging"]
AVAIL_DEF = ["—", "—", "—", "0.01", "0.01", "1/64", "40", "0", "block", "0", "0", "0", "dt_max", "0", "-1",
             "0", "0", "0", "mean", "none", "1", "off", "0", "0,0,0", "128", "4", "—", "1e-8", "1", "0", "0"]
PLANNED = []  # All keys of contracts/run-config.md are available now (T030, T032: 2026-11-07).

DOCS = [("README.md", "README"), (".specify/memory/constitution.md", "Constitution"),
        ("specs/001-hermite-nbody-lib/spec.md", "Spec"), ("specs/001-hermite-nbody-lib/plan.md", "Plan"),
        ("specs/001-hermite-nbody-lib/research.md", "Research"),
        ("specs/001-hermite-nbody-lib/contracts/run-config.md", "Run configuration contract"),
        ("specs/001-hermite-nbody-lib/tasks.md", "Tasks"), ("specs/001-hermite-nbody-lib/quickstart.md", "Quickstart"),
        ("docs/multi-node-design.md", "Multi-node design"), ("docs/cuda-best-practices.md", "CUDA best practices")]

# ---------------------------------------------------------------- per-language text
T = {}

T["en"] = dict(
    title="h4nb guide", subtitle="Direct N-body on NVIDIA GPUs: 4th-order Hermite, block time steps, FP64",
    status_note="✅ = works on <code>main</code> now. 🚧 = agreed design, not built yet (task number in brackets).",
    toc="Contents", lang_label="Language",
    s_problem="1. The problem",
    problem=f"""<p>A researcher studies a disk or a cluster around one heavy body: gas clouds around an active galactic nucleus (AGN), or stars around a central mass. The particles can have 10 % to 100 % of the central mass, so the central body moves.</p>
<ul><li><b>Exact forces:</b> every particle pulls on every other particle. One full force pass at N = 1 024 000 is about 10¹² pairs.</li>
<li><b>Controlled accuracy:</b> the maximum relative energy error over one mean orbital period is 1e-8 or less. A measured run must show it.</li>
<li><b>Speed:</b> large runs finish in hours on data-centre GPUs.</li>
<li><b>Reproducible:</b> same input, configuration, devices and build give the same output bit for bit.</li></ul>""",
    s_approach="2. The approach",
    approach_head=["Topic", "Decision", "Why"],
    approach=[["Integrator", "4th-order Hermite: predict, compute a and jerk, correct", "4th order with one force pass per step"],
              ["Time steps", "Aarseth criterion (η), power-of-two block steps, integer ticks", "Only active particles get a new force; exact block times"],
              ["Central body", "Particle 0, full participant", "Keeps momentum conserved"],
              ["Precision", "FP64 only, no fast-math, no float atomics, fixed sum order", "Accuracy and bit-identical runs"],
              ["Softening", "Optional Plummer ε; presets AGN 0.01, stellar 0.0001", "It changes the model; it does not hide errors"],
              ["Several GPUs", "Split sources (j-parallel); owner adds partials in order", "Few active particles per step; same work per GPU"],
              ["Several nodes ✅ (compiled; not run on GPUs)", "One MPI rank per GPU, CUDA-aware MPI, owner sums in rank order (T029–T036)", "Target: 4–8 GH200"],
              ["η", "Measure it per system; about 5e-4 for 1e-8", "The TZ range 0.001–0.02 does not reach 1e-8"],
              ["Speed work", "Each optimisation needs a measured gate", "GPU speed guesses are often wrong"]],
    s_arch="3. Architecture",
    arch="""<p>One public header (<code>include/h4nb/h4nb.hpp</code>) and one class, <code>Simulation</code>. No CUDA type in the API. The GPU kernels and the CPU test oracle share one math header (<code>src/hermite.cuh</code>).</p>
<p><b>One block step:</b></p><ol><li>Find the next block time Tn = min(next).</li><li>Predict all particles to Tn.</li><li>Select the active particles (next == Tn).</li><li>Send the active targets to every GPU.</li><li>Each GPU computes the partial a and jerk of its own sources on all targets (shared-memory tiles, one thread per target).</li><li>Send each slice to the owner GPU.</li><li>The owner adds the partials in device order, corrects, and chooses the new step.</li></ol>
<p>Memory: about 0.4 GB per GPU at 1M particles. Compute is the limit.</p>""",
    s_start="4. Quick start",
    start_build="Build (Linux x86_64 or aarch64, CUDA ≥ 12.0, CMake ≥ 3.24, GPU compute capability ≥ 7.0):",
    start_run="Run:",
    start_rule="<code>t_end</code>, <code>diag</code> and <code>snap</code> must be multiples of <code>dt_max</code> (default 1/64), and <code>diag</code> must divide <code>t_end</code>.",
    s_config="5. Configuration",
    cfg_avail="✅ Keys of <code>h4nb_run</code> (file, environment or command line, <code>key=value</code>):",
    cfg_keyhead=["Key", "Default", "Meaning"],
    cfg_meaning=["initial conditions (text or .snap)", "output directory", "end time", "Aarseth accuracy (use ≈0.0005 for 1e-8)",
                 "first step factor", "largest step (level 0)", "dt_min = dt_max / 2^max_level", "softening length ε",
                 "block or fixed", "level in fixed mode", "1: centre does not move (tests)", "GPU list, e.g. 0,1",
                 "energy record interval", "snapshot interval (multiple of diag)", "close-pair radius; 0 = off",
                 "expected particle count (0 = no check)", "ID of record 0 (central body)", "reference period (0 = estimate, needs G = 1)", "mean, median or mass_weighted", "none, agn (ε 0.01), stellar (ε 0.0001)", "gravitational constant", "off or linear_drag: a_diss = −(v − v_bg)/τ, not on particle 0; the verdict uses E − E₀ − W_diss", "drag time τ, > 0 with linear_drag", "background velocity v_bg (3 values)", "targets per block: 64, 128 or 256", "1 to 16", "explicit snapshot times", "energy verdict threshold", "0: no performance.dat",
                 "MPI only: GPU = (local rank + device_offset) % device count", "MPI only: 1 = copy MPI buffers through pinned host memory (MPI not CUDA-aware)"],
    cfg_sources="✅ Five sources. A later source wins:",
    cfg_src_list="<ol><li>default</li><li><code>preset=none|agn|stellar</code></li><li><code>config=&lt;file&gt;</code> (key=value lines)</li><li>environment <code>H4NB_&lt;KEY&gt;</code></li><li>command line</li></ol><p>An unknown key or a bad value is an error (exit code 2). Each run writes <code>config.used</code>. <code>help=1</code> prints all keys.</p>",
    cfg_planned_head=["🚧 Still planned", "Task"],
    cfg_choose="How to choose the main values",
    choose=[["eta", "Measure it with the η study. Start near 0.0005. Cost grows as 1/√η."],
            ["dt_max", "1/64 to 1/16 of the shortest period of interest."],
            ["max_level", "Raise it if you see the warning dt &lt; dt_min."],
            ["eps", "0 for point masses; preset=agn or preset=stellar for the two model types."],
            ["diag", "One energy check costs N²/2 pairs. At 1M use T/16 or more."],
            ["tile, blocks_per_sm", "Measure with h4nb_bench; keep the best values in the machine config."],
            ["GPUs / nodes", "Set by the launcher (devices=, mpirun, srun). The cluster size is not fixed in the code."]],
    s_cheat="6. Cheat sheet",
    cheat_cfg="Config file ✅", cheat_runcfg="Run with a config file ✅", cheat_mpi="Several nodes (MPI) ✅ compiled, GPU run pending", cheat_cpp="C++ ✅",
    cheat_out="Output files ✅",
    out=[["energy.dat", "time K U E rel_err max_rel_err mean_rel_err W_diss"], ["energy_periods.dat", "period t_start t_end max_rel_err mean_rel_err complete"], ["study/study.dat", "eta dt_max t_end max_rel_err ... pair_evals wall_s pass"], ["momentum.dat", "time Px Py Pz Lx Ly Lz dP_rel dL_rel"],
         ["timesteps.dat", "time dt_min dt_max dt_mean mean_active r_min"], ["performance.dat", "time wall_s block_steps active pairs_per_s"], ["bench/bench.dat", "N devices tile blocks_per_sm pairs_per_s gflops wall_s [pct_peak]"],
         ["snap_NNNNNN.snap", "binary: header + id m x y z vx vy vz"], ["config.used, run_info.txt", "configuration; commit, CUDA, GPUs, host, command"]],
    s_problems="7. Common problems",
    prob_head=["Symptom", "Cause", "Action"],
    problems=[["max |dE/E| &gt; 1e-8", "η too large", "Lower eta (try 0.0005, then 0.00025). Run the η study."],
              ["warning: dt &lt; dt_min", "A particle needs a finer step", "Raise max_level. Check close pairs."],
              ["warning: pair closer than r_close", "Close encounter", "Check r_min in timesteps.dat. Consider softening if the model allows it."],
              ["non-finite value (NaN or Inf)", "Bad input or a collision", "Check the input. The run stops by design."],
              ["advance_to: t must be a multiple of dt_max", "t_end, diag or snap not on the grid", "Use multiples of dt_max (1/64 = 0.015625)."],
              ["Build fails with arch native", "No GPU on the build machine", "Set CMAKE_CUDA_ARCHITECTURES=89 or 90."],
              ["Exit code 2 and a key=value message", "Unknown key, bad value or value out of range", "Read the message: it names the key, the value and the source. Run help=1."],
              ["1M run is very slow on RTX", "Low FP64 rate (1/64)", "Use RTX for N ≤ 131 072; use GH200 for 1M."],
              ["Results differ between GPU counts", "Different sum order", "Expected. Compare with the written tolerance, not bit for bit."]],
    s_hw="8. Hardware",
    hw_head=["GPU", "Use", "Note"],
    hw=[["RTX 4070 Ti (8.9)", "Development, N ≤ 131 072", "≈17 h per 1M period (estimate)"],
        ["GH200 (9.0)", "1M and production runs", "≈18 min per 1M period on one GPU (estimate)"],
        ["Below 7.0 (GTX 1060)", "Not supported", "Constitution 2.0.0"]],
    s_docs="9. Documents", generated="Generated from the repository documents by docs/guide/build_guide.py.",
)

T["it"] = dict(
    title="Guida h4nb", subtitle="N-body diretto su GPU NVIDIA: Hermite del 4° ordine, passi temporali a blocchi, FP64",
    status_note="✅ = funziona ora su <code>main</code>. 🚧 = progetto concordato, non ancora implementato (numero del task tra parentesi).",
    toc="Indice", lang_label="Lingua",
    s_problem="1. Il problema",
    problem="""<p>Un ricercatore studia un disco o un ammasso attorno a un corpo massiccio: nubi di gas attorno a un nucleo galattico attivo (AGN), oppure stelle attorno a una massa centrale. Le particelle possono avere dal 10 % al 100 % della massa centrale, quindi il corpo centrale si muove.</p>
<ul><li><b>Forze esatte:</b> ogni particella attrae tutte le altre. Un calcolo completo delle forze con N = 1 024 000 sono circa 10¹² coppie.</li>
<li><b>Precisione controllata:</b> l'errore relativo massimo dell'energia su un periodo orbitale medio è al massimo 1e-8. Lo deve dimostrare un'esecuzione misurata.</li>
<li><b>Velocità:</b> le simulazioni grandi terminano in ore su GPU da data center.</li>
<li><b>Riproducibilità:</b> stesso input, configurazione, dispositivi e build danno lo stesso output, bit per bit.</li></ul>""",
    s_approach="2. L'approccio",
    approach_head=["Tema", "Decisione", "Motivo"],
    approach=[["Integratore", "Hermite del 4° ordine: predizione, calcolo di a e del jerk, correzione", "4° ordine con un solo calcolo delle forze per passo"],
              ["Passi temporali", "Criterio di Aarseth (η), passi a blocchi in potenze di due, tick interi", "Solo le particelle attive ricevono nuove forze; tempi dei blocchi esatti"],
              ["Corpo centrale", "Particella 0, partecipante a pieno titolo", "Conserva la quantità di moto"],
              ["Precisione", "Solo FP64, niente fast-math, niente atomici float, ordine di somma fisso", "Precisione ed esecuzioni identiche bit per bit"],
              ["Softening", "Plummer ε opzionale; preset AGN 0.01, stellare 0.0001", "Cambia il modello; non nasconde gli errori"],
              ["Più GPU", "Sorgenti suddivise (j-parallel); il proprietario somma i parziali in ordine", "Poche particelle attive per passo; stesso lavoro per GPU"],
              ["Più nodi ✅ (compilato; non provato su GPU)", "Un rank MPI per GPU, MPI CUDA-aware, somma del proprietario in ordine di rank (T029–T036)", "Obiettivo: 4–8 GH200"],
              ["η", "Misurarlo per ogni sistema; circa 5e-4 per 1e-8", "L'intervallo 0.001–0.02 del TZ non raggiunge 1e-8"],
              ["Ottimizzazione", "Ogni ottimizzazione richiede una misura che ne mostri il bisogno", "Le stime di velocità su GPU sono spesso sbagliate"]],
    s_arch="3. Architettura",
    arch="""<p>Un solo header pubblico (<code>include/h4nb/h4nb.hpp</code>) e una sola classe, <code>Simulation</code>. Nessun tipo CUDA nell'API. I kernel GPU e l'oracolo CPU dei test condividono lo stesso header matematico (<code>src/hermite.cuh</code>).</p>
<p><b>Un passo a blocchi:</b></p><ol><li>Trovare il prossimo tempo di blocco Tn = min(next).</li><li>Predire tutte le particelle a Tn.</li><li>Selezionare le particelle attive (next == Tn).</li><li>Inviare i target attivi a ogni GPU.</li><li>Ogni GPU calcola a e jerk parziali delle proprie sorgenti su tutti i target (tile in shared memory, un thread per target).</li><li>Inviare ogni porzione alla GPU proprietaria.</li><li>Il proprietario somma i parziali nell'ordine dei dispositivi, corregge e sceglie il nuovo passo.</li></ol>
<p>Memoria: circa 0,4 GB per GPU con 1M particelle. Il limite è il calcolo.</p>""",
    s_start="4. Avvio rapido",
    start_build="Build (Linux x86_64 o aarch64, CUDA ≥ 12.0, CMake ≥ 3.24, GPU con compute capability ≥ 7.0):",
    start_run="Esecuzione:",
    start_rule="<code>t_end</code>, <code>diag</code> e <code>snap</code> devono essere multipli di <code>dt_max</code> (predefinito 1/64), e <code>diag</code> deve dividere <code>t_end</code>.",
    s_config="5. Configurazione",
    cfg_avail="✅ Chiavi di <code>h4nb_run</code> (file, ambiente o riga di comando, <code>key=value</code>):",
    cfg_keyhead=["Chiave", "Predefinito", "Significato"],
    cfg_meaning=["condizioni iniziali (testo o .snap)", "cartella di output", "tempo finale", "precisione Aarseth (≈0.0005 per 1e-8)",
                 "fattore del primo passo", "passo massimo (livello 0)", "dt_min = dt_max / 2^max_level", "lunghezza di softening ε",
                 "block o fixed", "livello in modalità fixed", "1: il centro non si muove (test)", "elenco GPU, es. 0,1",
                 "intervallo dei record di energia", "intervallo degli snapshot (multiplo di diag)", "raggio coppie vicine; 0 = spento",
                 "numero atteso di particelle (0 = nessun controllo)", "ID del record 0 (corpo centrale)", "periodo di riferimento (0 = stima, richiede G = 1)", "mean, median o mass_weighted", "none, agn (ε 0.01), stellar (ε 0.0001)", "costante gravitazionale", "off o linear_drag: a_diss = −(v − v_bg)/τ, non sulla particella 0; il verdetto usa E − E₀ − W_diss", "tempo di attrito τ, > 0 con linear_drag", "velocità di fondo v_bg (3 valori)", "target per blocco: 64, 128 o 256", "da 1 a 16", "tempi espliciti degli snapshot", "soglia del verdetto sull'energia", "0: niente performance.dat",
                 "solo MPI: GPU = (rank locale + device_offset) % numero di GPU", "solo MPI: 1 = buffer MPI copiati tramite memoria host pinned (MPI non CUDA-aware)"],
    cfg_sources="✅ Cinque sorgenti. Vince la sorgente successiva:",
    cfg_src_list="<ol><li>valore predefinito</li><li><code>preset=none|agn|stellar</code></li><li><code>config=&lt;file&gt;</code> (righe key=value)</li><li>variabili d'ambiente <code>H4NB_&lt;KEY&gt;</code></li><li>riga di comando</li></ol><p>Una chiave sconosciuta o un valore errato è un errore (codice di uscita 2). Ogni esecuzione scrive <code>config.used</code>. <code>help=1</code> stampa tutte le chiavi.</p>",
    cfg_planned_head=["🚧 Ancora previsto", "Task"],
    cfg_choose="Come scegliere i valori principali",
    choose=[["eta", "Misurarlo con lo studio di η. Partire da circa 0.0005. Il costo cresce come 1/√η."],
            ["dt_max", "Da 1/64 a 1/16 del periodo più breve di interesse."],
            ["max_level", "Aumentarlo se compare l'avviso dt &lt; dt_min."],
            ["eps", "0 per masse puntiformi; preset=agn o preset=stellar per i due tipi di modello."],
            ["diag", "Un controllo dell'energia costa N²/2 coppie. Con 1M usare T/16 o più."],
            ["tile, blocks_per_sm", "Misurarli con h4nb_bench; salvare i valori migliori nella config della macchina."],
            ["GPU / nodi", "Li imposta il launcher (devices=, mpirun, srun). La dimensione del cluster non è fissata nel codice."]],
    s_cheat="6. Promemoria",
    cheat_cfg="File di configurazione ✅", cheat_runcfg="Esecuzione con file di configurazione ✅", cheat_mpi="Più nodi (MPI) ✅ compilato, prova su GPU da fare", cheat_cpp="C++ ✅",
    cheat_out="File di output ✅",
    out=[],
    s_problems="7. Problemi comuni",
    prob_head=["Sintomo", "Causa", "Azione"],
    problems=[["max |dE/E| &gt; 1e-8", "η troppo grande", "Ridurre eta (provare 0.0005, poi 0.00025). Eseguire lo studio di η."],
              ["warning: dt &lt; dt_min", "Una particella richiede un passo più fine", "Aumentare max_level. Controllare le coppie vicine."],
              ["warning: pair closer than r_close", "Incontro ravvicinato", "Controllare r_min in timesteps.dat. Valutare il softening se il modello lo consente."],
              ["non-finite value (NaN or Inf)", "Input errato o collisione", "Controllare l'input. L'esecuzione si ferma per progetto."],
              ["advance_to: t must be a multiple of dt_max", "t_end, diag o snap fuori griglia", "Usare multipli di dt_max (1/64 = 0.015625)."],
              ["La build fallisce con arch native", "Nessuna GPU sulla macchina di build", "Impostare CMAKE_CUDA_ARCHITECTURES=89 o 90."],
              ["Codice di uscita 2 e un messaggio key=value", "Chiave sconosciuta, valore errato o fuori intervallo", "Leggere il messaggio: indica chiave, valore e sorgente. Eseguire help=1."],
              ["Esecuzione 1M molto lenta su RTX", "FP64 lento (1/64)", "Usare RTX per N ≤ 131 072; GH200 per 1M."],
              ["Risultati diversi con numero di GPU diverso", "Ordine di somma diverso", "Previsto. Confrontare con la tolleranza scritta, non bit per bit."]],
    s_hw="8. Hardware",
    hw_head=["GPU", "Uso", "Nota"],
    hw=[["RTX 4070 Ti (8.9)", "Sviluppo, N ≤ 131 072", "≈17 h per un periodo con 1M (stima)"],
        ["GH200 (9.0)", "Esecuzioni 1M e di produzione", "≈18 min per un periodo con 1M su una GPU (stima)"],
        ["Sotto 7.0 (GTX 1060)", "Non supportata", "Costituzione 2.0.0"]],
    s_docs="9. Documenti", generated="Generato dai documenti del repository con docs/guide/build_guide.py.",
)

T["uk"] = dict(
    title="Посібник h4nb", subtitle="Пряме N-body моделювання на GPU NVIDIA: Hermite 4-го порядку, блокові часові кроки, FP64",
    status_note="✅ = уже працює в <code>main</code>. 🚧 = погоджений дизайн, ще не реалізовано (номер задачі в дужках).",
    toc="Зміст", lang_label="Мова",
    s_problem="1. Проблема",
    problem="""<p>Дослідник вивчає диск або скупчення навколо одного масивного тіла: хмари газу навколо активного ядра галактики (АЯГ) або зорі навколо центральної маси. Сумарна маса частинок може становити від 10 % до 100 % центральної маси, тому центральне тіло рухається.</p>
<ul><li><b>Точні сили:</b> кожна частинка притягує всі інші. Один повний розрахунок сил для N = 1 024 000 — це приблизно 10¹² пар.</li>
<li><b>Контрольована точність:</b> максимальна відносна похибка енергії за один середній орбітальний період не перевищує 1e-8. Це має показати виміряний запуск.</li>
<li><b>Швидкість:</b> великі запуски тривають години на серверних GPU.</li>
<li><b>Відтворюваність:</b> ті самі вхідні дані, конфігурація, пристрої та збірка дають побітово той самий результат.</li></ul>""",
    s_approach="2. Підходи",
    approach_head=["Тема", "Рішення", "Чому"],
    approach=[["Інтегратор", "Hermite 4-го порядку: прогноз, обчислення a та jerk, корекція", "4-й порядок з одним розрахунком сил на крок"],
              ["Часові кроки", "Критерій Aarseth (η), блокові кроки степенями двійки, цілі ticks", "Нові сили отримують лише активні частинки; точні часи блоків"],
              ["Центральне тіло", "Частинка 0, повноправний учасник", "Зберігає імпульс"],
              ["Точність", "Лише FP64, без fast-math, без float-атоміків, фіксований порядок сум", "Точність і побітово однакові запуски"],
              ["Softening", "Необов'язковий Plummer ε; пресети АЯГ 0.01, зоряні 0.0001", "Змінює модель; не приховує похибки"],
              ["Кілька GPU", "Розподілені джерела (j-parallel); власник додає часткові суми в порядку", "Мало активних частинок на крок; однакова робота на GPU"],
              ["Кілька вузлів ✅ (скомпільовано; на GPU не перевірено)", "Один MPI rank на GPU, CUDA-aware MPI, власник сумує в порядку rank (T029–T036)", "Ціль: 4–8 GH200"],
              ["η", "Вимірювати для кожної системи; ≈5e-4 для 1e-8", "Діапазон ТЗ 0.001–0.02 не досягає 1e-8"],
              ["Оптимізація", "Кожна оптимізація потребує виміру, який показує потребу", "Припущення про швидкість GPU часто хибні"]],
    s_arch="3. Архітектура",
    arch="""<p>Один публічний заголовок (<code>include/h4nb/h4nb.hpp</code>) і один клас, <code>Simulation</code>. В API немає CUDA-типів. GPU-ядра та CPU-оракул тестів використовують один математичний заголовок (<code>src/hermite.cuh</code>).</p>
<p><b>Один блоковий крок:</b></p><ol><li>Знайти наступний час блоку Tn = min(next).</li><li>Спрогнозувати всі частинки до Tn.</li><li>Вибрати активні частинки (next == Tn).</li><li>Надіслати активні цілі на кожну GPU.</li><li>Кожна GPU обчислює часткові a та jerk своїх джерел для всіх цілей (тайли в shared memory, один потік на ціль).</li><li>Надіслати кожну частину GPU-власнику.</li><li>Власник додає часткові суми в порядку пристроїв, коригує і вибирає новий крок.</li></ol>
<p>Пам'ять: приблизно 0,4 ГБ на GPU для 1M частинок. Обмеження — обчислення.</p>""",
    s_start="4. Швидкий старт",
    start_build="Збірка (Linux x86_64 або aarch64, CUDA ≥ 12.0, CMake ≥ 3.24, GPU з compute capability ≥ 7.0):",
    start_run="Запуск:",
    start_rule="<code>t_end</code>, <code>diag</code> і <code>snap</code> мають бути кратними <code>dt_max</code> (за замовчуванням 1/64), а <code>t_end</code> має ділитися на <code>diag</code>.",
    s_config="5. Конфігурація",
    cfg_avail="✅ Ключі <code>h4nb_run</code> (файл, середовище або командний рядок, <code>key=value</code>):",
    cfg_keyhead=["Ключ", "За замовчуванням", "Значення"],
    cfg_meaning=["початкові умови (текст або .snap)", "папка результатів", "кінцевий час", "точність Aarseth (≈0.0005 для 1e-8)",
                 "множник першого кроку", "найбільший крок (рівень 0)", "dt_min = dt_max / 2^max_level", "довжина softening ε",
                 "block або fixed", "рівень у режимі fixed", "1: центр нерухомий (тести)", "список GPU, напр. 0,1",
                 "інтервал записів енергії", "інтервал знімків (кратний diag)", "радіус близьких пар; 0 = вимкнено",
                 "очікувана кількість частинок (0 = без перевірки)", "ID запису 0 (центральне тіло)", "опорний період (0 = оцінка, потрібно G = 1)", "mean, median або mass_weighted", "none, agn (ε 0.01), stellar (ε 0.0001)", "гравітаційна стала", "off або linear_drag: a_diss = −(v − v_bg)/τ, крім частинки 0; вердикт використовує E − E₀ − W_diss", "час гальмування τ, > 0 з linear_drag", "фонова швидкість v_bg (3 значення)", "цілей на блок: 64, 128 або 256", "від 1 до 16", "явні часи знімків", "поріг вердикту енергії", "0: без performance.dat",
                 "лише MPI: GPU = (локальний rank + device_offset) % кількість GPU", "лише MPI: 1 = буфери MPI через pinned-пам'ять хоста (MPI не CUDA-aware)"],
    cfg_sources="✅ П'ять джерел. Пізніше джерело перемагає:",
    cfg_src_list="<ol><li>значення за замовчуванням</li><li><code>preset=none|agn|stellar</code></li><li><code>config=&lt;file&gt;</code> (рядки key=value)</li><li>змінні середовища <code>H4NB_&lt;KEY&gt;</code></li><li>командний рядок</li></ol><p>Невідомий ключ або хибне значення — це помилка (код виходу 2). Кожен запуск записує <code>config.used</code>. <code>help=1</code> друкує всі ключі.</p>",
    cfg_planned_head=["🚧 Ще заплановано", "Задача"],
    cfg_choose="Як вибрати основні значення",
    choose=[["eta", "Виміряйте через дослідження η. Почніть з ≈0.0005. Вартість росте як 1/√η."],
            ["dt_max", "Від 1/64 до 1/16 найкоротшого періоду, що вас цікавить."],
            ["max_level", "Збільште, якщо бачите попередження dt &lt; dt_min."],
            ["eps", "0 для точкових мас; preset=agn або preset=stellar для двох типів моделей."],
            ["diag", "Одна перевірка енергії коштує N²/2 пар. Для 1M беріть T/16 або більше."],
            ["tile, blocks_per_sm", "Виміряйте через h4nb_bench; збережіть найкращі значення в конфігу машини."],
            ["GPU / вузли", "Задає лаунчер (devices=, mpirun, srun). Розмір кластера в коді не зафіксовано."]],
    s_cheat="6. Шпаргалка",
    cheat_cfg="Файл конфігурації ✅", cheat_runcfg="Запуск з файлом конфігурації ✅", cheat_mpi="Кілька вузлів (MPI) ✅ скомпільовано, запуск на GPU попереду", cheat_cpp="C++ ✅",
    cheat_out="Вихідні файли ✅",
    out=[],
    s_problems="7. Типові проблеми",
    prob_head=["Симптом", "Причина", "Дія"],
    problems=[["max |dE/E| &gt; 1e-8", "η завелике", "Зменште eta (спробуйте 0.0005, потім 0.00025). Запустіть дослідження η."],
              ["warning: dt &lt; dt_min", "Частинці потрібен дрібніший крок", "Збільште max_level. Перевірте близькі пари."],
              ["warning: pair closer than r_close", "Близьке зближення", "Перевірте r_min у timesteps.dat. Розгляньте softening, якщо модель дозволяє."],
              ["non-finite value (NaN or Inf)", "Хибні вхідні дані або зіткнення", "Перевірте вхідні дані. Запуск зупиняється навмисно."],
              ["advance_to: t must be a multiple of dt_max", "t_end, diag або snap не на сітці", "Використовуйте кратні dt_max (1/64 = 0.015625)."],
              ["Збірка падає з arch native", "На машині збірки немає GPU", "Задайте CMAKE_CUDA_ARCHITECTURES=89 або 90."],
              ["Код виходу 2 і повідомлення key=value", "Невідомий ключ, хибне значення або поза діапазоном", "Прочитайте повідомлення: там ключ, значення і джерело. Запустіть help=1."],
              ["Запуск 1M дуже повільний на RTX", "Повільний FP64 (1/64)", "RTX — для N ≤ 131 072; GH200 — для 1M."],
              ["Результати різні для різної кількості GPU", "Інший порядок сум", "Очікувано. Порівнюйте з записаним допуском, не побітово."]],
    s_hw="8. Обладнання",
    hw_head=["GPU", "Використання", "Примітка"],
    hw=[["RTX 4070 Ti (8.9)", "Розробка, N ≤ 131 072", "≈17 год на період для 1M (оцінка)"],
        ["GH200 (9.0)", "Запуски 1M і продакшн", "≈18 хв на період для 1M на одній GPU (оцінка)"],
        ["Нижче 7.0 (GTX 1060)", "Не підтримується", "Конституція 2.0.0"]],
    s_docs="9. Документи", generated="Згенеровано з документів репозиторію скриптом docs/guide/build_guide.py.",
)
T["it"]["out"] = T["en"]["out"]
T["uk"]["out"] = T["en"]["out"]

CSS = """
:root{--bg:#fff;--fg:#1d2330;--mut:#5b6474;--line:#dde2ea;--acc:#2456c9;--code:#f4f6fa;--head:#eef2f9}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#121620;--fg:#e4e8f0;--mut:#9aa4b5;--line:#2c3446;--acc:#7aa2ff;--code:#1b2130;--head:#1a2133}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:24px 16px 64px}
header{border-bottom:2px solid var(--acc);margin-bottom:16px;padding-bottom:8px}
h1{margin:0 0 4px;font-size:28px}.sub{color:var(--mut);margin:0}
.langs{float:right;font-size:13px}.langs a{margin-left:8px;color:var(--acc);text-decoration:none}.langs b{margin-left:8px}
.note{background:var(--head);border-left:4px solid var(--acc);padding:8px 12px;margin:12px 0;font-size:14px}
nav ol{columns:2;font-size:14px;padding-left:20px}nav a{color:var(--acc);text-decoration:none}
h2{border-bottom:1px solid var(--line);padding-bottom:4px;margin-top:32px;font-size:21px;break-after:avoid}
h3{font-size:16px;margin:18px 0 6px;break-after:avoid}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13.5px;break-inside:auto}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}th{background:var(--head)}
tr{break-inside:avoid}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;background:var(--code);padding:1px 4px;border-radius:3px}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:10px 12px;overflow-x:auto;break-inside:avoid}pre code{background:none;padding:0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.grid>div{min-width:0}
@media (max-width:720px){.grid{grid-template-columns:1fr}nav ol{columns:1}.langs{float:none;display:block;margin-bottom:6px}}
footer{margin-top:40px;color:var(--mut);font-size:12.5px;border-top:1px solid var(--line);padding-top:8px}
@media print{body{font-size:11.5px}.wrap{max-width:none;padding:0}pre{white-space:pre-wrap;word-break:break-all}a{color:inherit}.grid{grid-template-columns:1fr}}
"""

def page(lang):
    t = T[lang]
    langs = "".join(f"<b>{LANG_NAMES[l]}</b>" if l == lang else f'<a href="h4nb-guide.{l}.html">{LANG_NAMES[l]}</a>' for l in LANGS)
    secs = [("problem", t["s_problem"]), ("approach", t["s_approach"]), ("arch", t["s_arch"]), ("start", t["s_start"]),
            ("config", t["s_config"]), ("cheat", t["s_cheat"]), ("problems", t["s_problems"]), ("hw", t["s_hw"]), ("docs", t["s_docs"])]
    nav = "".join(f'<li><a href="#{i}">{html.escape(s.split(". ", 1)[1])}</a></li>' for i, s in secs)
    keys = table(t["cfg_keyhead"], [[k(a), k(b) if b != "—" else b, m] for a, b, m in zip(AVAIL_KEYS, AVAIL_DEF, t["cfg_meaning"])])
    planned = table(t["cfg_planned_head"], [[k(a), b] for a, b in PLANNED]) if PLANNED else ""
    docs = "<ul>" + "".join(f'<li><a href="{REPO}{p}">{n}</a> — <code>{p}</code></li>' for p, n in DOCS) + "</ul>"
    body = f"""
<section id="problem"><h2>{t['s_problem']}</h2>{t['problem']}</section>
<section id="approach"><h2>{t['s_approach']}</h2>{table(t['approach_head'], t['approach'])}</section>
<section id="arch"><h2>{t['s_arch']}</h2>{t['arch']}</section>
<section id="start"><h2>{t['s_start']}</h2><p>{t['start_build']}</p>{code(BUILD)}<p>{t['start_run']}</p>{code(RUN)}<p>{t['start_rule']}</p></section>
<section id="config"><h2>{t['s_config']}</h2><p>{t['cfg_avail']}</p>{keys}<p>{t['cfg_sources']}</p>{t['cfg_src_list']}{planned}
<h3>{t['cfg_choose']}</h3>{table(['', ''], [[k(a), b] for a, b in t['choose']]).replace('<thead><tr><th></th><th></th></tr></thead>', '')}</section>
<section id="cheat"><h2>{t['s_cheat']}</h2><div class="grid">
<div><h3>{t['cheat_cfg']}</h3>{code(CFG)}</div><div><h3>{t['cheat_runcfg']}</h3>{code(RUN_CFG)}</div>
<div><h3>{t['cheat_mpi']}</h3>{code(MPI)}</div><div><h3>{t['cheat_cpp']}</h3>{code(CPP)}</div></div>
<h3>{t['cheat_out']}</h3>{table(['', ''], [[k(a), k(b)] for a, b in t['out']]).replace('<thead><tr><th></th><th></th></tr></thead>', '')}</section>
<section id="problems"><h2>{t['s_problems']}</h2>{table(t['prob_head'], t['problems'])}</section>
<section id="hw"><h2>{t['s_hw']}</h2>{table(t['hw_head'], t['hw'])}</section>
<section id="docs"><h2>{t['s_docs']}</h2>{docs}</section>"""
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(t['title'])}</title><style>{CSS}</style></head><body><div class="wrap">
<header><span class="langs">{t['lang_label']}:{langs}</span><h1>{html.escape(t['title'])}</h1><p class="sub">{html.escape(t['subtitle'])}</p></header>
<div class="note">{t['status_note']}</div>
<nav><b>{t['toc']}</b><ol>{nav}</ol></nav>
{body}
<footer>{t['generated']} <a href="{REPO}docs/guide/build_guide.py">build_guide.py</a></footer>
</div></body></html>"""

def main():
    for lang in LANGS:
        (HERE / f"h4nb-guide.{lang}.html").write_text(page(lang), encoding="utf-8")
    if "--no-pdf" in sys.argv:
        return
    files = [str(HERE / f"h4nb-guide.{l}.html") for l in LANGS]
    js = """
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.emulateMedia({ colorScheme: 'light' });
  for (const f of %s) {
    await p.goto('file://' + f);
    await p.pdf({ path: f.replace(/\\.html$/, '.pdf'), format: 'A4', printBackground: true,
                  margin: { top: '14mm', bottom: '14mm', left: '12mm', right: '12mm' } });
  }
  await b.close();
})();""" % json.dumps(files)
    subprocess.run(["node", "-e", js], check=True)

if __name__ == "__main__":
    main()
