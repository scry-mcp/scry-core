# The names of the files a server writes

A file a server writes is named in lowercase ASCII letters and digits, in words joined by single
hyphens, then one dot and an extension of lowercase letters and digits (`snapshot-3.png`,
`f000012.png`): `^[a-z0-9]+(-[a-z0-9]+)*\.[a-z0-9]+$`. A value that comes from outside (an
argument, a profile, a system's name, the last component of a path the caller names) is
normalised into that rule by `scry_core.file_names`, or refused when nothing of it fits, and the
server's reply names the file that was written.
