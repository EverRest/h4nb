# Build and install h4nb with Spack

[Spack](https://spack.io) is a package manager for HPC systems. Use it to build h4nb on the development PC and on the GH200 cluster with the same commands.

Spack is a build and deploy tool only. It adds no library dependency to h4nb. The dependencies stay the same: the CUDA toolkit, the C++ standard library and, with `+mpi`, an MPI library (constitution, principle V).

## 1. Files

| File | Content |
| --- | --- |
| `spack/spack_repo/h4nb/packages/h4nb/package.py` | The Spack recipe for h4nb. |
| `spack/spack_repo/h4nb/repo.yaml` | The Spack package repository `h4nb`. |
| `spack/envs/dev-4070ti/spack.yaml` | The environment for the PC: 2x RTX 4070 Ti, `cuda_arch=89`, no MPI. |
| `tools/h4nb_release.sh` | Makes a release tag and adds the release to the recipe (`make release`, `make release-recipe`). |
| `spack/envs/gh200/spack.yaml` | The environment for the cluster: GH200, `cuda_arch=90`, `+mpi`, aarch64 (`neoverse_v2`). |

The two environments build this Git working tree (the `develop` section). Thus you build the code that you edit, not a fresh clone.

## 2. Variants

| Variant | Default | Effect |
| --- | --- | --- |
| `cuda_arch` | none | The GPU architectures. You must set it. Examples: `89` (RTX 4070 Ti), `90` (GH200), `89,90` (both). The recipe refuses values below `70`. It sets `CMAKE_CUDA_ARCHITECTURES`. |
| `+mpi` / `~mpi` | `~mpi` | `+mpi` builds the MPI path (`H4NB_MPI=ON`) and adds a dependency on a provider of `mpi`. |
| `cuda` | `+cuda` | h4nb needs CUDA. The recipe refuses `~cuda`. |
| `build_type` | `Release` | The CMake build type. |

The recipe needs CUDA 12.0 or newer and CMake 3.24 or newer.

## 3. Install Spack

Spack 1.0 or newer is necessary. The recipe uses the package API v2.2.

```bash
git clone --depth 1 -b v1.0.2 https://github.com/spack/spack.git ~/spack
. ~/spack/share/spack/setup-env.sh
spack compiler find
```

## 4. Build on the development PC (RTX 4070 Ti)

1. Open `spack/envs/dev-4070ti/spack.yaml`. Set the CUDA version and the CUDA prefix of the PC (`nvcc --version`, `which nvcc`).
2. Run these commands from the root of the repository:

```bash
spack env activate spack/envs/dev-4070ti
spack concretize -f
spack install
```

3. The tools are now in the environment view. They are on the `PATH`:

```bash
h4nb_bench
h4nb_run config=$(spack location -i h4nb)/share/h4nb/configs/agn.cfg ic=disk128k.snap out=run128k
```

After you change the code, run `spack install` again. Spack builds the working tree again.

## 5. Build on the GH200 cluster (MPI)

1. Find the CUDA toolkit and the MPI library of the cluster. For example: `module avail`, `module show cuda`, `module show openmpi`.
2. Open `spack/envs/gh200/spack.yaml`. Set the versions and the prefixes in the `externals` sections to the values of the cluster. If the cluster uses a different MPI (for example `cray-mpich` or `mpich`), change the `mpi` requirement and the external.
3. Use a CUDA-aware MPI. The design uses device pointers in the MPI calls ([multi-node-design.md](multi-node-design.md)).
4. Run these commands on a GH200 node, not on an x86_64 login node. Spack takes the CPU target of the node where it runs:

```bash
spack env activate spack/envs/gh200
spack concretize -f
spack install
```

5. Start the run with the launcher of the cluster. One rank per GPU:

```bash
srun -N 2 --ntasks-per-node=4 --gpus-per-task=1 h4nb_run config=... ic=... out=...
```

Do not let Spack build CUDA or MPI on the cluster. The cluster MPI knows the network and the scheduler. A Spack-built MPI often does not.

## 6. Build without an environment

```bash
spack repo add spack/spack_repo/h4nb
spack install h4nb cuda_arch=89                 # RTX 4070 Ti
spack install h4nb cuda_arch=90 +mpi            # GH200
spack install h4nb cuda_arch=89,90              # both architectures in one build
```

`spack install h4nb` without a version takes the highest release in the recipe. `h4nb@main` clones the `main` branch from GitHub. `h4nb@0.1.0` downloads the GitHub archive of the tag `v0.1.0`. These commands do not use the working tree.

## 7. Tests

`spack install --test=root h4nb ...` runs the tests with the label `cpu` (`ctest -L cpu`). The tests with the label `gpu` need a CUDA device. A build node often has no GPU. Run the `gpu` tests on a GPU node with `tools/h4nb_gpu_check.sh` or with `ctest -L gpu` in a build directory.

## 8. What the install contains

| Path in the prefix | Content |
| --- | --- |
| `bin/` | `h4nb_run`, `h4nb_mkdisk`, `h4nb_bench`, `h4nb_order`, `h4nb_study` |
| `lib/` | `libh4nb.a` |
| `include/h4nb/` | The public header `h4nb.hpp` |
| `share/h4nb/configs/` | The example configs (`agn.cfg`, `stellar.cfg`, `dev-4070ti.cfg`, `gh200.cfg`) |

`h4nb::build_info()` reports the Git commit. A build from the working tree reports the commit of the working tree.

## 9. Make a release

Spack does not publish packages like PyPI or npm. The recipe gives a list of versions. For each version, Spack downloads the GitHub archive of a Git tag and compares its sha256 with the recipe.

To make the release `0.1.0`, do these steps on the branch `main`:

1. Commit all the changes that the release must include.
2. Make the tag. The script does not push.

   ```bash
   make release VERSION=0.1.0       # makes the annotated tag v0.1.0 on HEAD
   git push origin main v0.1.0
   ```

3. Optional: make a GitHub release from the tag (`gh release create v0.1.0 --generate-notes`, or on the GitHub web page).
4. Add the version to the recipe. The script downloads the archive of the tag, calculates the sha256, adds `version("0.1.0", sha256="...")` and commits only the recipe. It does not push.

   ```bash
   make release-recipe VERSION=0.1.0
   git push origin main
   ```

5. On the cluster, get the new recipe (`git pull`). Then `spack install h4nb@0.1.0 cuda_arch=90 +mpi`.

The tag and the recipe line are in two different commits. This is correct: the recipe describes the tag, so it comes after the tag.

Do not move or delete a tag after you push it. The archive then changes, and Spack refuses the download because the sha256 is different. Make a new version instead (for example `0.1.1`).

A release build has no Git data. The recipe sets the CMake option `H4NB_SOURCE_VERSION=v0.1.0`. Then `build_info()` and `run_info.txt` report `v0.1.0` in place of the commit.

## 10. Later: submit the recipe to Spack

Now the recipe is in this repository (`spack repo add spack/spack_repo/h4nb`). Later you can submit it to the official package repository. Then `spack install h4nb` works for all Spack users without `spack repo add`.

1. Do this after the first GPU runs and a stable release (for example `1.0.0`). The Spack maintainers prefer packages with a release.
2. Fork [spack/spack-packages](https://github.com/spack/spack-packages).
3. Copy `package.py` to `repos/spack_repo/builtin/packages/h4nb/package.py` in the fork. Remove the comment lines about `make release-recipe`.
4. Run `spack style` and `spack audit packages h4nb`. Open a pull request.
5. For each new release, open a new pull request that adds one `version(...)` line.
