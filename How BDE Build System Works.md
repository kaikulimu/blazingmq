## How BDE Build System Works

#### How to Set Up
1. Set up directory structure according to BDE guidelines (i.e. `src/groups/xxx`) and add metadata files such as [`bmqa.dep`](https://github.com/bloomberg/blazingmq/blob/main/src/groups/bmq/bmqa/package/bmqa.dep) and [`bmqa.mem`](https://github.com/bloomberg/blazingmq/blob/main/src/groups/bmq/bmqa/package/bmqa.mem).
2. `git clone` [`bde-tools`](https://github.com/bloomberg/bde-tools) which contains [BdeBuildSystem](https://github.com/bloomberg/bde-tools/tree/main/BdeBuildSystem).
3. Set env var `DISTRIBUTION_REFROOT=/home7/mombot/bs/jaas/BMQ/refroot/Linux`, preferrably in [`CMakePresets.json`](https://bbgithub.dev.bloomberg.com/BMQ/bmq-enterprise/blob/33a719f3739a5833882f56a91a969b25524f03a6/CMakePresets.json#L20).
4. Run CMake with `-DCMAKE_MODULE_PATH="/path/to/bde-tools/cmake;/path/to/bde-tools/BdeBuildSystem"` and `-DCMAKE_TOOLCHAIN_FILE="/path/to/bde-tools/BdeBuildSystem/toolchains/darwin/gcc-default.cmake"`.

#### How It Works
1. We periodically [`refroot-install`](`https://tutti.prod.bloomberg.com/dpkg/reference/tools/dpkg-tools/refroot-install`) packages from [`bmq-unstable`](https://dpkg.dx.bloomberg.com/distributions/bmq-unstable/snapshots) DPKG distribution to refroot. See [Refroot Update](https://bbgithub.dev.bloomberg.com/pages/BMQ/help/refroot_update.html) internal docs for more details.
2. When our `xxx.dep` file lists a dependency package `<PackageName>`, BdeBuildSystem will check if it's a local package. If not, it will try to search for `.pc` files inside refroot using [`pkg-config`](https://www.freedesktop.org/wiki/Software/pkg-config/). If `pkg-config` is unsuccessful, it will call the [`find_package()`](https://cmake.org/cmake/help/latest/command/find_package.html) CMake function which looks for `Find<PackageName>.cmake`.
    - This omits the need to explicitly call `find_package(<PackageName>)` in our CMakeLists.txt.
