# Spack recipe for h4nb. See docs/spack.md.
#
# SPDX-License-Identifier: MIT

from spack_repo.builtin.build_systems.cmake import CMakePackage
from spack_repo.builtin.build_systems.cuda import CudaPackage

from spack.package import *


class H4nb(CMakePackage, CudaPackage):
    """CUDA direct N-body library: 4th-order Hermite integrator, block time
    steps, FP64, multi-GPU, optional MPI for several nodes."""

    homepage = "https://github.com/EverRest/h4nb"
    url = "https://github.com/EverRest/h4nb/archive/refs/tags/v0.1.0.tar.gz"
    git = "https://github.com/EverRest/h4nb.git"

    maintainers("EverRest")

    license("MIT")

    # Release versions: "make release-recipe VERSION=X.Y.Z" adds them below the line of main.
    # Spack prefers the highest release. It uses main only when you ask for h4nb@main.
    version("main", branch="main")

    # h4nb is a CUDA library. A build without CUDA is not possible.
    variant("cuda", default=True, description="Build with CUDA (required)")
    conflicts("~cuda", msg="h4nb needs CUDA")
    conflicts(
        "cuda_arch=none",
        when="+cuda",
        msg="Set cuda_arch, for example cuda_arch=89 (RTX 4070 Ti) or cuda_arch=90 (GH200)",
    )
    # Constitution: compute capability 7.0 or higher. Values such as "90a" have a letter suffix.
    for _arch in CudaPackage.cuda_arch_values:
        if int(_arch.rstrip("abf")) < 70:
            conflicts(f"cuda_arch={_arch}", msg="h4nb needs compute capability 7.0 or higher")

    variant(
        "mpi", default=False, description="Build the MPI path (one rank per GPU, several nodes)"
    )

    depends_on("cxx", type="build")
    depends_on("cmake@3.24:", type="build")
    depends_on("cuda@12.0:")
    depends_on("mpi", when="+mpi")

    def cmake_args(self):
        # A release archive has no Git data. build_info() then reports the tag, for example v0.1.0.
        source_version = "" if self.spec.satisfies("@main") else f"v{self.version}"
        return [
            self.define_from_variant("H4NB_MPI", "mpi"),
            self.define_cuda_architectures(self),
            self.define("H4NB_SOURCE_VERSION", source_version),
        ]

    def check(self):
        # Run only the tests with the label cpu. The gpu tests need a CUDA device,
        # and a build node often has none. Run them with tools/h4nb_gpu_check.sh.
        ctest = Executable(self.spec["cmake"].prefix.bin.ctest)
        with working_dir(self.build_directory):
            ctest("-L", "cpu", "--output-on-failure")
