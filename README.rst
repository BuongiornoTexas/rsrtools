

**rsrtools** is a package for creating and saving Rocksmith 2014 songlists **to** 
Rocksmith save files (profiles). Incidentally, it also provides tools for managing
Rocksmith profiles.

Acknowledgements
----------------

**@0x0L** for rs-utils and rocksmith Rocksmith tools. All of the save file and data file 
handling routines are based on this code.

**@sandiz** for rs-manager, which is an awesome set listing tool. This package also 
gave me a deeper understanding of the Rocksmith PSARC structure.

TODO
----
  - Convert major TODOs to issues.
  - Add whatever functionality is needed for rs-manager to use rsrtools as an
    integration option. 
  - Complete PSARC scanner (welder.py)
  - Convert song list configuration file from JSON to much more readable TOML.

Development notes
-----------------

20190420 The song list manager and database modules are functional and in beta testing.
Pending documentation update for 0.1 release.

20190328 The file managers and utilities are functional with the exception of the PSARC
scanner, which will be be added later. 
