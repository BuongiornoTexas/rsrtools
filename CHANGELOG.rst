Changelog
==========

**1.1.0** Behind the scenes stuff:

* Updated to python 3.12, minor code clean up. 

* Moved from toml to tomllib and tomli-w, much deferred pydantic update.
  
* Moved to hatch for packaging, shifted to src layout for packaging. 

* Older breaking items and Changelog moved to separate CHANGELOG file as a workaround
  for github rendering problems in early 2024.

**1.0.1** Minor update for changes in steam ``libraryfolder.vdf`` configuration,
minor bugfixes and linting. For anybody who is looking for a method to merge
Rocksmith profiles, I've also put together a rough script as a gist - 
`profilemerge.py 
<https://gist.github.com/BuongiornoTexas/c781d28b35ebdfd0ba7f6d906b0cad4a>`_
Be extremely careful using this script - minimal error check and review. 
I'd suggest creating a test profile, clone data into it, and then merge data 
into that.

**1.0.0** First full release based on no issues being reported for a significant period.
Includes a minor update to allow underscore and dash characters in importrsm song list
names (this addresses a bug identified in
`rs-manager issue 68 <https://github.com/sandiz/rs-manager/issues/68#issuecomment-604780122>`_).

**0.3.5beta 2019-05-21** Song list filters will now pick up songs that have never
been played (previously a song needed to have been played at least once for the database
queries to fire). Fixed spurious detection of new DLC in songlists.

**0.3.0beta 2019-05-21** Feature complete release (barring a GUI in the longer term
future). The main feature added in this release is welder/welder.py for packing and
unpacking PSARC files, and the integration of the song scanner into the song list
module. This means rsrtools can now operate in stand alone mode. This also allows
improved path (lead/rhythm/bass) filters for song list creation.

**0.2.2beta 2019-05-08** Arrangement deletion cli.

**0.2.1beta 2019-05-05** Minor bug fixes, added profile db path option to importrsm.

**0.2.0beta 2019-05-01** This release provides a command line tool for importing song 
lists/set lists exported from `rs-manager <https://github.com/sandiz/rs-manager>`_. With
this functionality, you can take advantage of rs-manager's flexible GUI to generate set
lists, export them to file, and then save them to a Rocksmith profile using rsrtools. 
As of version 2.1.2, rs-manager supports this capability out of the box. Unless you have
a particular desire to roll your own rsrtools filters, I'd suggest this as a recommended
use case. The documentation below provides further details on importrsm. 

- Added field reports to song list cli, moved steam.py.

- Fixed a major oversight and added an export profile as json method to profile manager.

- Added a command line importer for song lists/set lists exported from rs-manager.

- Added entry points for profilemanager, songlists and importrsm.

**0.1.2beta 2019-04-26** Mac OS X support added. 

**0.1.1beta 2019-04-26** Minor updates to refer to Steam account id and Steam user id 
correctly. All Steam support functions moved to steam.py. Some Windows specific Steam
functions removed and replaced with methods based on Steam vdf files.

**0.1.0beta 2019-04-22** First functional beta release for rsrtools. Windows only.

**0.0.1 2019-03-12** Place holder release to lock package name down in pypi.