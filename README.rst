.. cSpell:ignore venv, Analyzer, userdata, remotecache, PRFLDB, pypi, profilemanager
.. cSpell:ignore docstrings, dict, CDLCs, tuple, stats, simplejson, importrsm
.. cSpell:ignore faves, newlist

**rsrtools** is a package for creating and saving Rocksmith 2014 songlists **to** 
Rocksmith save files (profiles). Incidentally, it also provides tools for managing
Rocksmith profiles.

.. contents::

Acknowledgements
================

**@0x0L** for `rs-utils <https://github.com/0x0L/rs-utils>`_ and 
`rocksmith <https://github.com/0x0L/rocksmith>`_ Rocksmith 
tools. All of the save file and data file handling routines are based on this code.

**@sandiz** for `rs-manager <https://github.com/sandiz/rs-manager>`_, which is an 
awesome set listing tool. This package also gave me a deeper understanding of the 
Rocksmith PSARC structure.

News and Breaking Changes
==========================

**1.1.0** **WARNING** Please back up your config.toml before upgrading, as this change
may break it! Update to python 3.12, minor code clean up. Moved from toml to tomllib,
tomli-w.  I had no issues with Windows 11, but if you are on an older version, you may
need to convert your config.toml from Windows text to UTF-8 format (I believe it should
work out of the box though).

**1.0.1** Minor update for changes in steam ``libraryfolder.vdf`` configuration,
minor bugfixes and linting. For anybody who is looking for a method to merge
Rocksmith profiles, I've also put together a rough script as a gist - 
`profilemerge.py 
<https://gist.github.com/BuongiornoTexas/c781d28b35ebdfd0ba7f6d906b0cad4a>`_
Be extremely careful using this script - minimal error check and review. 
I'd suggest creating a test profile, clone data into it, and then merge data 
into that.

**1.0.0** First full release. No major changes from 0.3.5.

**0.3.0** Feature complete release (barring a GUI in the longer term future).
The main feature added in this release is welder/welder.py for packing and unpacking 
PSARC files, and the integration of the song scanner into the song list module. This
means rsrtools can now operate in stand alone mode. This also allows improved 
path (lead/rhythm/bass) filters for song list creation.

**0.2.0**  As of version 
`2.1.3 <https://github.com/sandiz/rs-manager/releases/tag/v2.1.3>`_,  
rs-manager integrates rsrtools support out of the box. This means you can install 
rs-manager and rsrtools, and then export set lists/song list directly from rs-manager 
into your Rocksmith profile.

**0.2.0** This release provides a command line tool for importing song lists/set lists
exported from `rs-manager <https://github.com/sandiz/rs-manager>`_. With this
functionality, you can take advantage of rs-manager's flexible GUI to generate set lists,
export them to file, and then save them to a Rocksmith profile using rsrtools. Unless
you have a particular desire to roll your own rsrtools filters, I'd suggest this as 
a recommended use case. The documentation below provides further details on importrsm. 

Warnings
========

As this package is all about editing game saves, here are a couple of warnings.

0. This package is in Beta. I've been using it for more than a year, and
   it has been robust for my application. However, until this warning disappears,
   please assume that you are the second ever user and that you will find bugs.   
   Please report these to me via github issues so I can implement fixes.

1. This package edits Rocksmith profiles. Use at your own risk and with the 
   understanding that this package carries the risk of corrupting your save files
   (to date it has worked fine for me - YMMV, and it will definitely stop working if
   Ubisoft make any changes to the Rocksmith save file format). However, the package
   includes many self checks and tries to make backups of profiles before making
   changes, so the risk of profile loss or corruption should be low.

2. This package is (obviously) not endorsed by Ubisoft - if you use this package and run
   into problems with your save files, Ubisoft will not be very interested in helping
   you. If this happens, I will try to help, but will be limited by my available time
   and the complexity of your problem. So, in effect repeating the previous warning: use
   this package at your own risk.

3. **Don't run this package at the same time as  Rocksmith is running.** You'll end up 
   crossing the save files and nobody will be happy (mostly you though).

4. This package will only work on Windows and Mac OS X at the moment. I have no idea
   what would be needed for Linux/PS4/XBox song lists.


TL:DNR
======

If you know what you are doing with python, here are the recommended quick start steps.

Installation and Basic Set Up
------------------------------

0. The package only works on Windows and Mac OS X for now.

1. Install python 3.7.x (I'm on 3.7.3, and you will need some 3.7 features).

2. Create a virtual environment (for easy step by step instructions, see 
   `Installation and Set Up`_). 

3. Install rsrtools into your virtual environment with::

    pip install rsrtools

4. Create a working folder/directory.

5. **READ** the section on setting up a test profile (`Set up a Testing Profile!`_). 
   Until you are familiar with the package, this will be your best safeguard against 
   damaging your precious save game(s).

6. **SET UP** a Rocksmith test profile. Open Rocksmith, create a new profile named e.g.
   'Testing', and run through the profile set up (unavoidable).

7. Optional, but highly recommended: **Clone your save game into the test profile** and
   do all of your testing on this test profile until you are comfortable that the
   package is working and doing what you want it to do (`Clone Profile`_). The following
   command provides a short cut for profile cloning::

      profilemanager --clone-profile <path_to_your_working_directory>

   Profile cloning is destructive - make sure you get your source and your target
   correct! 

Running importrsm from rs-manager
----------------------------------

Go to settings and check that the path to importrsm is correct. After that, you should
be able to use the rs-manager export buttons to save set lists/song lists to a Rocksmith
profile.

Running importrsm Stand Alone
-------------------------------

You can get help for the rs-manager importer by running either of::

    importrsm -h
    python3 -m rsrtools.importrsm -h

If you have two song list JSON files ``faves.json`` and ``newlist1.json`` that you want
to import into Favorites and song list 3, the following command will get you started::

    importrsm <path_to_your_working_directory> -sl F faves.json -sl 3 newlist1.json

This will perform basic checks on the JSON files and will prompt you for a Steam 
account and a Rocksmith profile (remember to use your test profile while you are trying
things out!), and finally will ask you to confirm the file write. Most of these steps
can be automated and the logging silenced - refer to the help for more details.

Using rsrtools
---------------

If you'd like to use rsrtools filters, the steps are:

1. Start your virtual environment and run the package (with appropriate substitution for
   ``<path_to_your_working_directory>``)::

        songlists <path_to_your_working_directory>

   Or, if you'd rather not use an entry point::

        python3 -m rsrtools.songlists.songlists <path_to_your_working_directory>

   If you start in the working directory, you could use::

    songlists .

2. Try out the test filters, reports and song lists, and then move on to creating your
   own in ``config.toml``. Remember to use your test profile!

Python Entry Points
====================

**New in 0.2.0**. The package supports, and this documents assumes, use of python entry
points for the profile manager, the song list creator, and the song list importer.

This means you can run these tools by specifying an explicit path to the location you
have installed them into. For example, for a Windows install to ``D\RS_Stuff\Env``, the
commands are::

        D:\RS_Stuff\Env\songlists.exe
        D:\RS_Stuff\Env\profilemanager.exe
        D:\RS_Stuff\Env\importrsm.exe

Or, for a Mac OS X install to ``~/Documents/RS_Stuff/Env``::

        ~/Documents/RS_Stuff/Env/songlists.exe
        ~/Documents/RS_Stuff/Env/profilemanager.exe
        ~/Documents/RS_Stuff/Env/importrsm.exe

If you'd rather use python directly, or if you don't want to type command paths, you
will need to *activate your virtual environment* and use one of the following command
forms. For Windows::

        py -m rsrtools.songlists.songlists
        songlists
        songlists.exe

        py -m rsrtools.files.profilemanager
        profilemanager
        profilemanager.exe

        py -m rsrtools.importrsm
        importrsm
        importrsm.exe

For Mac OS X::

        python3 -m rsrtools.songlists.lists
        songlists

        python3 -m rsrtools.files.profilemanager
        profilemanager

        python3 -m rsrtools.importrsm
        importrsm

The sections on `Installation and Set Up`_, 
`Importing Song Lists Created by rs-manager`_, 
and `Creating Song Lists with rsrtools`_ explain how to set up and activate virtual
environments. 

You can use whichever approach works better for you. The remainder of the document 
assumes environment activation and commands without paths, but in practice, I tend to 
alternate depending on what I'm doing. 

Motivation
==========

Hopefully this section doesn't read too much like a food blog.

I've implemented this package because, while I really enjoy Rocksmith 2014 Remastered as
a learning tool, I've had ongoing frustration with creating custom play lists. I 
thought there had to be a better way (and I also wanted a project I could use to learn
python). My initial goal for this package was to be able to easily create song lists for
a specific tuning and play counts - I break my practice sessions up into new stuff,
moderately new and old - and it's a real pain in the backside scrolling through 500 
odd tracks. And it's also a pain in the backside setting up custom song lists in
Rocksmith. So that's the motivation for this project. During implementation, I realised
it would be possible to create much more varied song lists (not so useful for me, but
maybe so for others).

Introduction
============

The purpose of this package is to provide an improved song list creator for Rocksmith.
This package allows creation of song lists based on a variety of criteria, and allows
the criteria to be built up hierarchically. Here is an incomplete list of the type of 
song lists you can create with this package.

- All lead arrangements with E Standard tunings (not very exciting).

- All songs with E Standard tunings at 440 pitch (still not exciting).

- All lead D standard 440 songs with a played count between 12 and 18 (getting somewhere
  now).

- All bass Eb standard 440 songs with a mastery between 40 and 65%.

- All E standard songs that I have played at least once on score attack, but haven't got
  a platinum badge (yet).

- All easy E Standard songs that I haven't yet got a platinum badge for (OK. So it's a
  long list for me, but something to work on).

- All rhythm songs with an alternative or bonus arrangement, but no songs that have no
  alternative or bonus arrangement.

I'm simplifying a bit here, but it gives an idea of the type of thing that this
package is intended to do. 

Criteria that can be used for song list creation include:

* List criteria:

  - Tuning

  - Path (Lead, Rhythm, Bass)

  - Sub-Path (Representative - the default track for a path, Bonus or Alternative)

  - ArrangementName (Bass, Lead, Lead1, Lead2, Lead3, Rhythm, Rhythm1, Rhythm2, Combo,
    Combo1, Combo2, Combo3)

  - Song key (typically the unique part of DLC/song file names)

  - ArrangementId (expert functionality)

  - Artist Name

  - Track Title

  - Album Name

* Range criteria:

  - Album Year

  - Pitch (A440 or otherwise)

  - Tempo

  - Note Count

  - Played Count

  - Mastery Peak

  - SA Easy Badges

  - SA Medium Badges

  - SA Hard Badges

  - SA Master Badges

  - Song Length

  - and a few more.

Filtering can be by inclusion or exclusion. A more complicated example would be: all 
E Standard, D Standard and C Standard lead tracks, but nothing by the Foo Fighters or
Green Day and nothing in the decade 2000-2010, only tracks I haven't completed a hard
platinum score attack, and only tracks I've played at least 4 times. (I can't imagine
using this filter myself, but somebody with a grudge against Dave Grohl might care).

If you want a particular type of song list and can't see how to build it from the help, 
ask me and I'll see if I can either come up with a solution or add the needed 
functionality.

Alternatives
============

1. The Customs Forge Song Manager (CFSM) provides a different 
   mechanism for creating song lists based on moving files in and out of directories.
   My approach provides some of the same functionality, with the following variations:

   - I don't move song files, but rather edit the song lists directly in the Rocksmith
     profiles/save files.

   - I support building song lists based on data in save files (played counts, score 
     attack performance, mastery, etc.). 
     
   The CFSM approach is very actively supported, 
   so if you aren't interested in the specific functionality my approach provides, I'd
   go with their tool, which is available from: http://customsforge.com/.

2. rs-manager (https://github.com/sandiz/rs-manager) is a GUI application that can 
   create set lists manually or from procedural filtering similar to rsrtools. It is a
   much friendlier way to generate song/set lists than rsrtools. @sandiz, the 
   rs-manager developer, has implemented functionality to run rsrtools from within 
   rs-manager. This process is described below (`rs-manager Song List Export`_), and is
   likely to be the recommended use case for most people.
   
   Alternatively, rs-manager can export set lists in a format that can be used by 
   rsrtools. As of 0.2.0, rsrtools allows loading of these set lists into Rocksmith save
   files. This allows a work flow where set lists can be generated using the rs-manager
   GUI and then exported for loading into Rocksmith by rsrtools (bypassing the joys of
   setting up text filters for rsrtools). This process is a manual version of the 
   process used by rs-manager, so is only of interest to those who want fine grained
   control of the process.

That's the Long Intro over. 

Documentation and Tutorial
==========================

The documentation provided here is fairly detailed. I've done this on the basis that
a significant portion of users will be interested in using the system, but not 
interested in the details of the python. Consequently, there is a lot of step by step
detail included. If you know your way around python, you should be able to skim through
a lot of the content very quickly (and you can modify the set up to match your own
environment).

This package provides:

- A command line tool for reading song lists created by rs-manager and writing these 
  song lists into a Rocksmith profile. The work flow for this process is described below.

- A command line tool for creating Rocksmith song lists from a series of filters, and
  writing the resulting song lists into a Rocksmith profile. The command line work flow
  is described below.

- A set of routines that can be used to implement a GUI version of the command line
  tools (I have not implemented a GUI, as the command line is sufficient for my
  requirements - see the section on `Alternatives`_ for more GUI oriented solutions).

Repeated warning (`Warnings`_): this package is currently only supported on Windows 
(tested on Windows 10) and Mac OS X (tested on High Sierra).

Installation and Set Up
========================

* Download and install Python 3.7+ from www.python.org. (I'd recommend 3.7.3, which is 
  what I'm using).

* Create a folder/directory for running rsrtools. For this tutorial, I'm assuming this 
  is: ``D:\RS_Stuff``, and create an environment sub-directory ``Env`` and a working 
  sub-directory ``Working`` in the rsrtools directory. At the end of this step, my 
  folders are::

       D:\RS_Stuff
       D:\RS_Stuff\Env
       D:\RS_Stuff\Working

  For a Mac OS X user working in ``~/Documents``, this might look like::

       ~/Documents/RS_Stuff
       ~/Documents/RS_Stuff/Env
       ~/Documents/RS_Stuff/Working

I will continue to use these directory paths for the remainder of this document. Please
adjust your paths to reflect your own set up.

* Set up a python virtual environment for rsrtools and install the package via pip. If
  you are unfamiliar with python, follow these steps:
  
  1. Open a command window (cmd.exe).

  2. Type the following commands. The hashed lines are comments that explain what each
     command does and can be ignored::
        
        # Change paths as required to match your rsrtools directory
        # Create the environment in D:\RS_Stuff\Env
        python -m venv "d:\RS_Stuff\Env"

        # Activate the python environment
        "d:\RS_Stuff\Env\Scripts\activate.bat"

        # install rsrtools and supporting libraries
        pip install rsrtools

     Or, for a Mac OS X user::

        python3 -m venv ~/Documents/RS_Stuff/Env
        . ~/Documents/RS_Stuff/Env/scripts/activate
        pip install rsrtools

  3. Exit the command window.

Set up a Testing Profile!
===========================

Until you are confident that this package is working properly, I **strongly** suggest
you use a temporary testing Rocksmith profile. I'd also suggest trying all new song list
imports/filters on the testing profile before applying them to your main profile.

The process I follow for testing changes before applying them to my main profile is:

- Create the Testing profile (described in this section).

- Clone my profile into the Testing profile. This is very useful if you want to test 
  song lists based on played counts, score attack, mastery, etc. The next section
  explains how to clone your profile.

- Try out the song list filters/imports on the Testing profile.

The process for setting up a temporary profile is about as easy as it gets:

a. Start Rocksmith.

b. At the Select Profile Menu, click New Profile, name the profile and go through set up
   (the set up step can't be avoided unfortunately).

Clone Profile
==================

**Optional, but recommended**. Clone data into the Testing profile. If you clone data
from your main profile, you can test out the song list filters/imports before 
overwriting the song lists in your main profile.

I'll assume we are cloning data in the Steam account with description 
``'12345678', (HalfABee [eric])`` and we want to clone the profile 
``'Eric the Half a Bee'`` into ``'Testing'``. This will replace all data in the 
Testing profile.

There are two ways to access profile cloning. Both require that you activate your python
environment first. As ever, adjust paths to reflect your own set up.

1. From the profile manager command line for Windows::

        Call "D:\RS_Stuff\Env\Scripts\Activate.bat"
        profilemanager --clone-profile "D:\RS_Stuff\Working

   Or, for Mac OS X::

        . ~/Documents/RS_Stuff/Env/scripts/activate
        profilemanager --clone-profile ~/Documents/RS_Stuff/Working

   Select Steam account '12345678' for profile cloning.

2. From the songlists command line for Windows::

        Call "D:\RS_Stuff\Env\Scripts\Activate.bat"
        songlists "D:\RS_Stuff\Working"

   Or, for Mac OS X::

        . ~/Documents/RS_Stuff/Env/scripts/activate
        songlists ~/Documents/RS_Stuff/Working

   If this is the first time you have run songlists, you will need to wait for a
   a scan of your songs to complete (30 seconds to a couple of minutes depending on how
   many songs you own and the speed of your computer).

   Select the 'Change/select Steam account id' menu option, and then select Steam
   account '12345678' for profile cloning.

   Select the 'Utilities' option, and then select the 'Clone profile' option. 

In either case, you should now have the profile cloning menu up.

**Make sure you get the next two right**. Cloning destroys data in the profile you are
copying to (the target).

Select the source profile for cloning. For the tutorial, I'm copying **FROM** 
'Eric the Half a Bee'.

Select the target profile for cloning. For the tutorial, I'm copying **TO** 
'Testing'.

A yes/non confirmation message will pop up. Check that the cloning operation is
doing what you expect, and if so choose y.

Return to the main menu and exit the program. If you are asked, there is no need to save
config changes this time.

Now is a good time to start up Rocksmith and check the Testing profile:

* To see that it still works after cloning.

* To check that the data from your main profile has been copied in correctly.

rs-manager Song List Export
=============================

This section describes using `rs-manager <https://github.com/sandiz/rs-manager>`_
to export a set list/song list directly into a Rocksmith profile. I am expecting this
will be the main use case use for most rsrtools users. 

0. Install both rsrtools and rs-manager.

1. Start rs-manager.

2. Go to settings and check that the path to importrsm is correct. 

3. Go to Set Lists, pick a set list, hit the export button, and follow the prompts

That's it!

Importing Song Lists Created by rs-manager
===========================================

This section explains how to use the importrsm command line program to read
song lists created and exported by `rs-manager <https://github.com/sandiz/rs-manager>`_,
and then write these song lists to a Rocksmith profile.

Repeating an important warning (`Warnings`_): **Don't run this package at the same time
as  Rocksmith is running.** You'll end up crossing the save files and nobody will be
happy (mostly you though).

For this section, I'll assume you have created a couple of song lists with rs-manager,
and that the files ``list1.json``, ``list2.json``, ``list3.json`` have been saved to
your working directory (and as before this is either ``D:\RS_Stuff\Working`` or 
``~/Documents/RS_Stuff/Working``).

Running the rs-manager importer is straightforward - you need to activate your python
environment and run importrsm with a working directory and a set of command line
options. For Windows, this looks like::

        Call "D:\RS_Stuff\Env\Scripts\Activate.bat"
        importrsm "D:\RS_Stuff\Working" <options>

Or, for Mac OS X::

        . ~/Documents/RS_Stuff/Env/scripts/activate
        importrsm ~/Documents/RS_Stuff/Working <options>
    
I'll go through each of the options in turn. First up, you can specify one or more song
lists to import. Each song list is specified as either::

      -sl <destination> <filename>
      --song-list <destination> <filename>

<destination> is the destination for the song list, and must be F for Favorites or a
number from 1-6 for those song lists, and <filename> is the name of the rs-manager
song list/set list file. For example::

    -sl F list2.json -sl 3 list3.json -sl 2 list1.json

will write the songs in list2.json to Favorites, list3.json to song list 3 and 
list1.json to song list 2. If you don't supply any additional arguments, importrsm will
start an interactive process to select a Steam account and the Rocksmith profile that
will be updated with the new song lists.

If you'd rather not deal with the interactive account process, you can use the following
options to specify a Steam account and Rocksmith profile::

    -a <Steam_account_identifier>
    --account-id <Steam_account_identifier>
    -p <profile_name>
    --profile <profile_name>

importrsm is relatively smart about Steam_account_identifier - this can be an account
name, and account alias, an 8 digit account id or a 17 digit Steam id. Profile name
must the be name as used in Rocksmith.

Finally, you can use ``--silent`` to disable logging and interactive prompts (but then
you must provide at least one song list specification and Steam account and Rocksmith
profile arguments), and ``--no-check`` to disable checking of song key strings. 

For more details on these options, consult the help for importrsm::

    importrsm -h

Creating Song Lists with rsrtools
=====================================

This section explains how to use the songlists command line program to generate
song lists from pre-defined filters, and how to write these song lists to a Rocksmith
profile. The following sections explain how to set up these filters.

Repeating an important warning (`Warnings`_): **Don't run this package at the same time
as  Rocksmith is running.** You'll end up crossing the save files and nobody will be
happy (mostly you though).

Preliminaries
-------------

1. Create a working directory that will contain working copies of Rocksmith files, the 
   arrangement database, and the song list configuration file. For this tutorial I will 
   use the folder/directory set up in the previous section::

       D:\RS_Stuff\Working

2. Optional, but strongly recommended: Create a temporary/testing profile and clone your
   main profile into it - see `Set up a Testing Profile!`_ and `Clone Profile`_ for 
   details.

3. Because I'm lazy, at this point I put together a batch file in the working 
   directory. Let's call it 'song_lists.bat' and put the following lines in it::

        echo on
        Call "D:\RS_Stuff\Env\Scripts\Activate.bat"
        songlists "D:\RS_Stuff\Working"
        Deactivate.bat

   Or, for a Mac OS X user, create a shell script containing::

        . ~/Documents/RS_Stuff/Env/scripts/activate
        songlists ~/Documents/RS_Stuff/Working
        deactivate

   You will need to edit your paths to match where you have put your python environment
   and your working directory.

   When I say run the batch file below, I suggest that you do this initially from a 
   command shell (cmd.exe). This will allow you to see any errors (otherwise if you 
   double click on the batch file, the screen will flash up and close before you have a 
   chance to read anything). Once you are confident everything is working, you can run
   it with a double click.

4. Run the batch file to set up the default configuration. If this is the first time
   you have run songlists, you will need to wait 30s to a couple of minutes while it 
   scans your song library. After this, you should see a text menu something like the
   following::

      Rocksmith song list generator main menu.

          Steam account id:    'not set'
          Rocksmith profile:   'not set'
          Reporting to:        Standard output/console
          Working directory:   D:\RS_Stuff\Working

      Please choose from the following options:

        1) Change/select Steam account id. This also clears the profile selection.
        2) Change/select Rocksmith player profile.
        3) Toggle the report destination.
        4) Choose a single filter and create a song list report.
        5) Choose a song list set and create a song list report.
        6) Choose a song list set and write the list(s) to Song Lists in the Rocksmith profile.
        7) Choose a filter and write the resulting song list to Favorites in the Rocksmith profile.
        8) Utilities (database reports, profile management.)
        0) Exit program.
        h) Help.

      Choose>

   All of the text menus and text prompts will ask you to either select a number or 
   select y/n (followed by enter to action).

7. At this menu, you first need to select a Steam account id, so choose 1 to start a
   text menu for selecting from the available Steam account ids. For this tutorial, our 
   selection options look like this::

      Please select a Steam account id/Rocksmith file set from the following options.

      1) Steam user '12345678', (HalfABee [eric]), most recent Steam login. (Sun Apr 4 15:32:52 2019).
      0) Do nothing and raise error.

   We get a bit of help here - only one Steam id is available, and it is the user most
   recently logged into steam with a profile name/alias of HalfABee and a steam account
   name of eric. So we choose 1 to select user ``12345678``.

   Most people will only have one account id available - if you have more than one, you 
   may need a bit of trial and error to work out which one in is yours. The easiest way
   to do this is select an id and then check if the Testing profile can be selected
   (next step). If not, you have the wrong Steam id and need to try another one.

8. After selecting a Steam id, you need to select a user profile for song list creation.
   Choose 2 to start this process, and then choose a profile ('Testing' for this
   tutorial). After completing this process, the first two information lines of the 
   song list menu should be similar to::

            Steam account id:    '12345678', (HalfABee [eric]), most recent Steam login.
            Rocksmith profile:   'Testing'

9. At this point, it's worth saving the changes you have made.

   Select 0 to exit the program.

   You will then be offered the option to save changes to the configuration file. Choose y.

   After this, your working directory should contain the following files and 
   sub-directories::

     ArrangementsGrid.xml    - If you put this file in the working directory.
     RS_Arrangements.sqlite  - The song list arrangements database.
     config.toml             - The default configuration file. Heart and brains of the 
                               system. More on this below.
     song_lists.bat          - If you created it.
     .\RS_backup             - Backups of Rocksmith save files will be stored here.
     .\RS_update             - Changed save files will be stored here before copying
                               back to Steam.
     .\RS_working            - Save files will be copied from Steam to this folder 
                               before working on them.

   If your working directory doesn't match this, try this step again.


Generating and Saving Song Lists
-----------------------------------

The package is now set up with a default configuration, which you can use for some
basic testing before creating your own song list filters - or you can skip this step
and go straight to making your own.

Run the batch file and check that the Steam account id and profile are as expected::

        Steam account id:     '12345678'
        Rocksmith profile:    'Testing'

Experiment with the reporting options:

- Toggle between reporting to file and console (File reports are saved in the 
  working directory).

- Test out reports on a single filter and on a filter set.

If you are reporting to the console, you will almost certainly need to scroll up to 
see the report output, as the song list menu takes up most of the normal console 
window.

Also experiment with the reporting options in the utility sub-menu. These reports 
may be useful when developing your own filters.

If you are happy with the reporting, you can try writing one of the default song list 
sets to Rocksmith - either ``"E Standard"`` for lead players or ``"Bass or Rhythm"``
for bass and rhythm players. Before you do this, I would recommend doing a text report
for the song list set and checking it looks sensible. And finally, before writing
to Rocksmith, please remember that this is going to **replace** existing song lists
in the profile (use a test profile for testing!).

The default E Standard song list for lead players will create the following song lists:

1. E Standard 440 leads that have been played 0-12 times in Learn a song.

2. E Standard 440 leads that have been played 13-27 times in Learn a song.

3. E Standard 440 leads that have been played 27 or more times in Learn a song.

4. E Standard songs with an off concert pitch (i.e. not A440) that have been played 
   once.

5. E Standard lead tracks that have a bonus or alternative arrangement.

6. All E Standard songs that you have played in easy score attack, but haven't 
   yet got a platinum pick.
  
The bass or rhythm song list set generates a similar set of song lists.

Once you have written a song list set to Rocksmith, exit the package, open up Rocksmith,
load the test profile and check the song lists to see if they match expectation (song
lists 1, 2 or 3 may be empty you if haven't played any songs that match the filter
criteria. 

If you are happy with all of this, the next step is to edit ``config.toml`` to 
create your own song list filters.

The Configuration File
======================

All song lists are driven by the ``config.toml`` file in the working directory. This 
section describes the structure of this file. If you end up with major problems with
this file, I suggest renaming the problem file and creating a new config file by
following the set up steps in the tutorial (you can also try contacting me for help).

TOML is somewhat similar to windows .ini files. I've used it because it is a human 
readable/editable text form that "just works" and because python appears to be leaning 
towards it as a standard for configuration files. It's a bit fiddly to edit 
for the data structures used in rsrtools, but it's nowhere near as bad as JSON (which
was the likely alternative).

Unfortunately, if any of the the TOML is malformed, the song list creator will throw an
error and exit.  However, when this happens, you will (hopefully) get an informative 
error message that will help you track the problem down. And a gotcha - the input is 
validated in two stages - some checking when loading, and some checking values when 
creating the song lists. So your debugging may need to be two stage as well. I'd also
suggesting setting up one song list at a time to minimise your pain.

TODO I'm planning to put together some form of primitive filter builder as part of the 
next round of updates

I suggest that you open and look at ```config.toml``` while reading the rest of this
section.

The configuration file is broken into three sections::

      [settings]
      ...
      
      [filters]
      ...

      [song_list_sets]
      ...

Note that correct parenthesis type and double quoting is vital, and ``...`` shows 
something I will fill in more detail on later. For this section, text should be typed
as shown with the exception of text in angle brackets ``<>``, which represents user
defined names and input. You should replace both the angle brackets and the guide text 
with your own text. For example:

- ``"<filter name>"`` would become ``"E Standard"``.
- ``"<value 1>"`` would become ``"David Bowie"``.
- ``<list field name>`` would become ``Tuning``.

Note that double quoting is typically required where shown -- this provides protection
for fields with spaces and non-standard characters. The only fields that do not need
double quoting are ``<list field name>`` and ``<range field name>``
as these have a limited set of valid values, and none of them contain spaces or special
characters. The values for ``include`` (true or false) and ``ranges`` (numbers) must not
be quoted, and the values for ``mode`` (``"AND"``, ``"OR"``) should be quoted.

Settings
--------

The settings section is the simplest of the three, describing the location of the CFSM 
xml file (this will disappear in future), the default Steam account id, the default
profile name, and the date of the most recent song dlc scanned::

      [settings]
      CFSM_file_path: "D:\\RS_Stuff\\Working\\ArrangementsGrid.xml"
      steam_account_id": "12345678"
      player_profile": "Testing"
      version = "x.x.x"
      dlc_mtime = 1553292870.944582

Version is for future functionality.

Song List Sets
---------------

The song list sets section is just about this simple as the settings - each song list 
set is a named list containing up to six filter names that will be used to create the 
song lists in the Rocksmith profile (the next part of this section describes
filter definitions). The following example shows the structure::

    [song_list_sets]
    "E Standard" = [ "E Std Low Plays", "E Std Mid Plays", "E Std High Plays", 
        "E Std Non Concert", "", "Easy E Std Plat Badge in progress",]
    "Non E Std Tunings" = [ "Drop D", "Eb Standard", "Eb Drop Db", "D Standard", 
        "D Drop C", "Other Tunings",]
    Testing = [ "Artist test", "Played Count of 1 to 15",]

The song list set names are "E Standard", "Non E Std Tunings", and "Testing". You can
choose your own unique names for filter sets when you add them. The "E Standard" song 
list set consists of five unique filters - three filters for E 440 with differing play
counts, an E standard non 440, and an easy platinum score attack in progress filter. It
also includes "" for the fifth filter - this tells the song list creator to leave the 
fifth song list in the profile unchanged.

In summary, the format of a song list set is::

    "<set name>" = [ "<filter 1>", "<filter 2>", "<filter 3>", ... "<filter 6>"]

where the values in <> are the song list set names, the filter names or empty to skip
a song list (``""``).

The song list creator will only modify as many song lists as there are filters defined
(up to six), and will not change any list with "" specified for the filter. 
So the "Testing" filter set will only modify song list one and two and will leave lists
3-6 unchanged.

Filters
--------

The filters section consists of a list of named filters, where each named filter is made
up of the following elements:

- The basic filter definition (one only per filter).
- One or more sub-filters, which in turn may be either list type or range type.

The following sections detail these elements.

Basic Filter Definition
++++++++++++++++++++++++

A basic filter definition has the form::

      [filters."<filter name>"]
      base = "<base filter name>"
      mode = "<mode value>"

The filter can either have a base filter, in which case the filter criteria will be
applied to records generated from the base filter, or if base filter is the empty string
(``""``) the filter will be applied to all records in the arrangements database. 
That is, the base filter is an optional field that allows building of nested or
hierarchical filters. 

Mode must be either ``"AND"`` or ``"OR"``, and specifies the way that sub-filters will
be combined. For ``"AND"``, the filter will only return the records that match all of the
sub-filters, while for ``"OR"``, the filter will return all records that match at least
one of the sub-filters (i.e. AND narrows, while OR is inclusive).

List Type Sub-filter
+++++++++++++++++++++

The list type sub-filter is of the form::

        [filters."<filter name>".sub_filters.<list field name>]
        include = <true or false>
        values = [ "<value 1>", "<value 2>", ... , "<value N>",]

``<list field name>`` must be one of the list type field names::

          SongKey
          Tuning
          ArrangementName
          ArrangementId
          Artist
          Title
          Album
          Path
          SubPath
   
The utilities menu includes an option to list all of these field names.

SubPath has three valid values: Representative, Alternative and Bonus.

``include`` must be ``true`` or ``false``. If ``true``, the filter will return the
records for song arrangements whose field value matches any of the values in the list. If 
``false``, the filter will return the records for song arrangements whose field value 
does not match any of the values in the list. E.g. if the field name is Artist and 
the values are "Queen" and "Roxette", then an include value of true will return only 
song arrangements by Queen and Roxette. If include is false, then all arrangements
except songs by Queen and Roxette will be returned.

The list values must match values in the arrangements data and must be double quoted - 
the easiest way to check on validity is to run the relevant reports in the utilities
menu of the song list creator (e.g. Tunings, Arrangement Types, Artists, Album Names
and Track Titles).

**GOTCHA**: Values must be exact matches on content and case. So "E Standard" works,
but "e standard" doesn't, likewise it must be "Foo Fighters", and not "Foo f" or 
"foo fighters". I may add wild card support at some point in the future if there is
strong support for it.

Range Type Sub-filter
++++++++++++++++++++++

The range type sub-filter is of the form::

        [filters."<filter name>".sub_filters.<range field name>]
        include = <true or false>
        ranges  = [ [<low1>, <high1>], [<low2>, <high2>] ]

``<range field name>`` must be one of the range type field names::

        Pitch
        Tempo
        NoteCount
        Year
        PlayedCount
        MasteryPeak
        SAEasyCount
        SAMediumCount
        SAHardCount
        SAMasterCount
        SAPlayedCount
        SAEasyBadges
        SAMediumBadges
        SAHardBadges
        SAMasterBadges
        SongLength

The utilities menu includes an option to list all of these field names.

A note of caution: I'm pretty sure the MasteryPeak values are *not quite right*. At the
moment, I'm calculating these by multiplying the raw mastery peak value from the player
profile by 100. However, this value doesn't quite match the reported value in Rocksmith.
I can fix this quickly if anybody knows the correct calculation.

SA stands for score attack, SA*Count is the score attack play account at the level, and
SAPlayedCount is the total score attack play count. 

The SA*Badges values have the following meanings:

- 0 No badge/not played yet. 
- 1 Strike out/three red crosses.
- 2 Bronze/two red crosses
- 3 Silver/one red cross
- 4 Gold
- 5 Platinum

When I set up a badge filter, I'm normally only interested in songs I have played and 
haven't yet got a a platinum badge for, so I use a range value of  [[1, 4]]. I generally
filter zero out, as otherwise the filter returns all un-played arrangements.

``include`` must be ``true`` or ``false``. If ``true``, the filter will return only
those song arrangement records that have field values in the ranges specified in the 
``ranges`` list. If false, the filter will return those song arrangement records that
have field values that do not appear in any of ranges in the ``ranges`` list.

``ranges`` is a list of numeric low/high value pairs. The only constraint on the values 
is that they must be greater than or equal to zero. Note that the number values are not
double quoted. If you enter a low value that is greater than the high value, the
package will assume you have your numbers backward and will swap them silently.

For example, for a field name of ``PlayedCount`` and ``ranges = [[1,10],[18,19]]`` and
``include = true``, the filter will return all arrangements with Learn a Song play count
in the range 1 to 10 or 18 to 19. If ``include`` is ``false``, the filter will
return all arrangements that have a play count that is either: 0, in the range 11 to 17,
or greater than or equal to 20.

Filter Examples
---------------

The following examples taken from the default set of filters illustrate most of the
filter features.

First up, a filter for songs with (mostly) lead arrangements::

        [filters."Lead-ish"]
        base = ""
        mode = "OR"

        [filters."Lead-ish".sub_filters.Path]
        include = true
        values = [ "Lead", ]

        [filters."Lead-ish".sub_filters.Title]
        include = true
        values = [ "Should I Stay or Should I Go", "Blister in the Sun",]

This filter is interpreted as follows:

- The filter is named "Lead-ish".

- It does not have a base filter, so it will apply the filter to the entire record set
  in the arrangement database.

- There are two sub-filters. The first filter includes all arrangements that are on 
  the lead path. The second filter includes the arrangements for two songs: Should I
  Stay or Should I go by the Clash, and Blister in the Sun by the Violent Femmes.

- The ``"OR"`` mode combines the results of the sub-filters. 

In effect, this filter results in the records for all arrangements that are lead type
along with the arrangements for the named songs. This filter ensures that I can see all
lead tracks and the two named tracks, which only have bass and rhythm arrangements, but
I still want them to appear in my song lists.

The following filter narrows the lead-ish filter to E Standard tunings::

    [filters."E Standard"]
    base = "Lead-ish"
    mode = "AND"

    [filters."E Standard".sub_filters.Tuning]
    include = true
    values = [ "E Standard",]

This nested filter is interpreted as taking the records generated by the 
"Lead-ish" filter and keeping only those arrangements with an E Standard tuning.

The final filter generates a list of E Standard tunings which are off concert pitch 
(i.e. not A440 tunings)::

        [filters."E Std Non Concert"]
        base = "E Standard"
        mode = "AND"

        [filters."E Std Non Concert".sub_filters.Pitch]
        include = false
        ranges = [ [ 439.5, 440.5,],]

        [filters."E Std Non Concert".sub_filters.PlayedCount]
        include = true
        ranges = [ [ 1.0, 5000.0,],]

This filter builds on the results of the "E Standard filter" by keeping only records
which:

- Have a pitch outside the range 439.5 to 440.5 Hz (``include = false``). That is, this 
  removes all A440 tunings, 
- **AND** (mode = ``"AND"``) have a play count between 1 and 5000 (i.e. this removes
  tracks with a play count of zero - at least if like me, none of your play counts are
  within any sort of distance of 5000).

Nested vs. Flat Filters
-----------------------

The examples in the previous section demonstrate how to build up filters using a nested
or hierarchical approach. 

This nesting capability improves re-usability of filter logic and makes assembling 
complex filters quite a lot simpler. (This mechanism could definitely be improved 
further still, but hey, it's only a simple play list creator.)

You can build also build up a complex filters by using multiple sub-filters in a single
filter. For example, something close to the nested filters for the off concert pitch 
E Standard arrangements could have been built in with a single filter applying the
following sub-filters::

        [filters."One Step E Std Non Concert"]
        base = ""
        mode = "AND"

        [filters."One Step E Std Non Concert".sub_filters.Path]
        include = true
        values = [ "Lead",]

        [filters."One Step E Std Non Concert".sub_filters.Tuning]
        include = true
        values = [ "E Standard",]        

        [filters."One Step E Std Non Concert".sub_filters.Pitch]
        include = false
        ranges = [ [ 439.5, 440.5,],]

        [filters."One Step E Std Non Concert".sub_filters.PlayedCount]
        include = true
        ranges = [ [ 1.0, 5000.0,],]

(This is something close, because it's not possible to build a one shot filter like this
that also capture the Clash and Violent Femmes arrangements).


To date I have always found the most effective way to build the filters is to 
use simpler filters based on one or two sub-filters, and then build complexity by 
nesting. (Either way is fine of course, so go with whatever works best for you.)

Something Went Wrong!
======================

Something unexpected has happened with loading a profile in Rocksmith? All is (probably)
not lost. Before rsrtools writes files to the Rocksmith Steam folders, it creates a 
zip archive of **all** of the key files associated with the Steam account id. These
backups are kept in the working directory under ``RS_backup``.

To restore a backup, extract the contents of the zip file and copy the contents into
your Steam Rocksmith save folder. For most people, this should be in your Steam
install directory under::

    <Steam directory>\userdata\<steam_account_id>\221680

``<steam_account_id>`` is the same Steam account id used in the rsrtools songlists menu.

As a check, this folder should contain a ``remotecache.vdf`` file and a ``remote``
sub-directory. The ``remote`` subdirectory should contain a file named 
``LocalProfiles.json`` and one or or more files with names ending in ``_PRFLDB``.

Database Structure
===================

For those who are interested, the database is structured as two tables, which contain
song arrangement data and player performance data. The filters are executed on a join
of these two tables.

The string fields are the same fields defined in the `List Type Sub-filter`_ section, 
and the numeric fields are those defined in the `Range Type Sub-filter`_ section.

Package Caveats
===============

Be aware that the package currently has a couple of irritating quirks:

- It can't distinguish between the representative (default) arrangement on a path and 
  the alternative/bonus arrangements on that path (i.e. it can't tell which of the leads
  is the default).

- A related issue. It can't tell which path Rocksmith (OG) combo tracks should be
  allocated to.

I know how to resolve the issue, but it is waiting on the song scanner implementation. 
The way I work around this is to play all of the tracks that I want to show up in a 
filter at least once, and then apply a minimum play count criteria. For my use case, 
this is mainly an issue for E standard arrangements - I don't tend to worry about this
for the alternate tunings.

Sidebar: Rocksmith Save File Editing
======================================

The primary purpose of this package is to provide facilities for customising Rocksmith 
song lists. However, along the way I needed to develop classes for opening, editing
and saving Rocksmith save files (profiles). 

If you are interested in using this functionality, you should start with 
RSProfileManager in profilemanager.py, which is the primary class for managing
Rocksmith profiles and their associated steam *and* Rocksmith metadata. The class
methods are currently only documented in their docstrings, although I plan to provide
more detail in this document in the future (and I'm happy to answer questions via
github issues).

Profile Editing Examples
--------------------------

The best example of a save file editor is importrsm.py - I deliberately structured this
module to act as sample/template for editors using the RSProfileManager class. The 
main() function is structured as follows:

- Argument parsing.

- Loading and validating data.

- Selecting Steam account and Rocksmith profile.

- Calls to functions that demonstrate the two ways of modifying save data (detailed in
  the next section).

- Writing updates to the working folder, and then moving the updated files to steam.

The RSProfileManager class provides two more simple examples of profile editing:

- ``RSProfileManager.cl_edit_action()`` and ``RSProfileManager.set_play_counts()``, 
  which provide a command line mechanism for setting the 'Learn a Song' play counts for
  one or more song arrangements.
- ``RSProfileManager.cl_clone_profile()``, which is a command line mechanism for
  cloning a player data from one profile into another (a destructive copy). 

(For a more brutal edit style, command line arrangement id deletion is implemented by:
``RSProfileManager.cl_edit_action()`` and 
``RSProfileManager.delete_profile_arrangements()``.)

Both of these routines can be run from the command line. For further details see the
profile manager help, which can be obtained from the command line::

    profilemanager -h

The song list creator also uses the profile manager to obtain player data and to write
song lists into player profiles.

Aside from importrsm, these methods either a) implement very small changes to save files
with a lot of care to maintain Rocksmith formats (see `Notes on Formats`_), or b) 
replace Rocksmith data with Rocksmith data. Consequently their implementations are
buried within classes used by the profile manager.

Roll Your Own Editor
----------------------

If you want to make more general changes to Rocksmith profiles, you can use the 
methods::

    RSProfileManager.get_json_subtree()
    RSProfileManager.set_json_subtree()
    RSProfileManager.mark_as_dirty()

``importrsm.py`` illustrates how to use these methods in the functions: 
``import_faves_by_replace`` and ``import_song_lists_by_mutable``. To date, this is the
only place I have used (and tested) these get/set json routines. As these routines are
very simple, I would expect them to work without problem in other applications. However,
given the limited testing, bugs are possible, so please be careful with your save files
(in case you haven't heard it before - use a Testing profile!). 

(If you want a somewhat safer path for changes to Rocksmith save files, please make a
feature request on github and we'll see what we can work up. )

I also suggest you review the `Notes on Formats`_ section which discusses how to ensure
any edits you make conform as closely as possible to the Ubisoft file format (and hence
maximise your chances of profile edits loading successfully).

With those warnings out of the way, onto the approach. The general steps are:

0. Export a profile in JSON format so that you can work out which fields and data
   you want to work with in your editor. To this end, rsrtools includes a handy profile 
   export feature described in `Exporting Human Readable Profiles`_.

1. Create a profile manager instance (pm), which will need a working directory.

2. Read json data from a profile using::

     pm.get_json_subtree(profile_name, json_path).
   
   Keep in mind this may return a mutable (list, dict), in which case, editing the
   json data is effectively editing the profile data. (My preferred approach is to edit
   a copy and write the copy back using ``set_json_subtree``). If you do choose to edit
   a mutable json object, you need to let the profile manager know that you have done
   this by calling::
   
      pm.mark_as_dirty(profile_name)

3. If you are working on new data, a copy of data obtained from get_json_subtree, or a 
   non-mutable value, replace the instance data in the profile manager with the new
   data by::
   
      pm.set_json_subtree(profile_name, json_path, new_values)

   This approach will automatically mark the instance data for profile_name as dirty.

4. Write the files to the update folder (and generate backups along the way)::

      pm.write_files()

5. Move the updated files to the Steam folder::

      pm.move_update_to_steam(steam_account_id)
 
   Note that it's up to you to ensure that the save files match up with the
   steam account id (the method doesn't check this).

And finally, a brief explanation of json_path: the get/set_subtree methods use a JSON 
path to navigate save data elements in the Rocksmith profile JSON dictionary. A JSON
path is a list or tuple of the elements used to locate a specific value or subtree in
the save data. E.g. the json_path to song list 2 is::

        ('SongListsRoot', 'SongLists', 1)

and the Learn a song play count for Take Me Out is::

      ("Stats", "Songs", "AB6880DBE00E6E059A5B8449873BE187", "PlayedCount")

(I grabbed the Take Me Out Arrangement Id of AB6880DBE00E6E059A5B8449873BE187 from
an rsrtools report.)

Exporting Human Readable Profiles
----------------------------------

In their raw form, Rocksmith profiles are human readable(-ish) JSON objects. Rocksmith
compresses and encrypts these objects before saving the profiles to disk (distinctly
not human readable). 

rsrtools includes facilities to export the JSON objects as text. The simplest method
is to do the export from the utilities menu of rsrtools. Alternatively, you can also
run a command line tool::

        profilemanager --dump-profile <path_to_your_working_directory>

This tool will ask you to select a steam account and a Rocksmith profile and then
will export the profile data into the working directory as '<profile_name>.json'.

Notes on formats
------------------

As a general principle, I recommend using the JSON exported from a save file created by
**Rocksmith** (and not one created by rsrtools!) as a template for any editing that you
want to apply to save files. 

The things that I pay particular attention to are:

- Strings vs values. In particular, integers are sometimes treated as string values, and
  sometimes treated as numbers with six decimal places. Make sure you follow whatever 
  Rocksmith does!
- From the checking I've done so far, Rocksmith appears to treat *all* numeric values as
  real numbers with six decimal digits. I use code on the following lines to ensure
  integers are presented in this format::

    from decimal import Decimal

    json_6d_value = Decimal(
      integer_value
    ) + Decimal("0.000000")

  This method converts the integer to a Decimal and forces the 6 digit precision used
  by Rocksmith. You will need to apply a similar approach to convert floats to a 
  6 digit Decimal (I haven't needed to do this yet). 

  For an implementation example, see ``set_arrangement_play_count()`` in the 
  ``RSProfileManager`` class.

Note that rsrtools imports all numeric values as Decimal types, and I would recommend
that you ensure any edits you apply to numeric values in the JSON dictionary also have
a Decimal type to ensure decimal precision is maintained in the profile (rsrtools
implements this via the simplejson library, which has handles for Decimal objects).

PSARC Handling
================

The entry point executable welder(.exe) supports the following PSARC functions:

- Extract: extract single or multiple files from a PSARC archive.

- List: List files in a PSARC.

- Pack: Pack the contents of a directory into a PSARC file.

- Unpack: Unpack a PSARC.

- Verify: Verify a PSARC.

For further options, run ``welder -h`` (many of the options relate to debugging and 
verification). 

In general, I would recommend using other tools for working with PSARC files (e.g. 
the Rocksmith Custom Song Tool Kit). I implemented this module to allow scanning of
PSARC files for metadata and out of curiosity about how the files work. I've done a
reasonable amount of testing for my purposes, but this is probably insufficient for
anybody who wants to work on CDLCs. 

TODO
=====

- Remove deprecated CFSM functions.

- Convert major TODO items to issues.

- Add more substantial documentation on profile manager (for Rocksmith file editing),
  database, and song lists (hooks for GUI implementations).

Changelog
==========

**1.0.0** First full release based on no issues being reported for a significant period.
Includes a minor update to allow underscore and dash characters in importrsm song list
names (this addresses a bug identified in
`rs-manager issue 68 <https://github.com/sandiz/rs-manager/issues/68#issuecomment-604780122>`_).

**0.3.5beta 2019-05-21** Song list filters will now pick up songs that have never
been played (previously a song needed to have been played at least once for the database
queries to fire). Fixed spurious detection of new DLC in songlists.

**0.3.0beta 2019-05-21** Welder module for PSARC packing/unpacking. Scanner built into
songlists.

**0.2.2beta 2019-05-08** Arrangement deletion cli.

**0.2.1beta 2019-05-05** Minor bug fixes, added profile db path option to importrsm.

**0.2.0beta 2019-05-01** 

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

Development notes
=================

20190421 Song list creator and database modules functional, first draft of documentation
complete. 0.1 release imminent.
