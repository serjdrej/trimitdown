# Vendored tiktoken BPE cache

The single hash-named file here is the `cl100k_base` byte-pair-encoding table that
[tiktoken](https://github.com/openai/tiktoken) normally downloads on first use. It is 1.6 MB
of encoding data — no code, nothing executable.

It is committed on purpose. The token counter has to work offline: the desktop build is a
single PyInstaller binary that runs with no network, and the Docker image should not reach out
during a conversion. Both build targets copy this directory in, and `TIKTOKEN_CACHE_DIR` points
tiktoken at it.

The filename is tiktoken's own cache key (a hash of the table's download URL), so it must not
be renamed. To refresh it, delete the file and run any conversion once on a machine with
network access — tiktoken re-downloads it under the same name.
