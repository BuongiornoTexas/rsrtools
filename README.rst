

**Rsrtools** is a package for creating and saving Rocksmith 2014 songlists **to** 
Rocksmith save files (profiles). Incidentally, it also provides tools for managing
Rocksmith profiles.

TODO
----
    - Convert major TODOs to issues.
    - Add whatever functionality is needed for rs-manager to use rsrtools as an
      integration option. 
    - Complete PSARC scanner (welder.py)
    - Convert song list configuration file from JSON to much more readable TOML.

Development notes
-----------------

20190328 Song list manager functions to be added. Work in progress, not recommended for
use at the moment.

20190328 File managers and utilities functional with the exception of the PSARC scanner
- to be added later. Not particularly useful by themselves. 

20190319 package files to be added over the next few weeks as I complete my QA.

Acknowledgements
----------------

  0x0L for rs-utils and rocksmith Rocksmith tools. All of the save and data file 
  extraction is based on this code.

  rs-sandiz for rs-manager, which is an awesome set listing tool. This package also 
  gave me a deeper understanding of the Rocksmith PSARC structure.
