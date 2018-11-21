# (c) Copyright 2013-2019 University of Manchester
'''
 plugin_name: Import GAMS
	          Import a gdx results file into Hydra.

A Hydra plug-in to import results from a GAMS model run. All results need to
be stored in a *.gdx file (the GAMS proprietary binary format). Also, variables
that will be imported need to be present in HydraPlatform, before results can
be loaded. We strongly recommend the use of a template.

Basics
~~~~~~

The GAMS import plug-in provides an easy to use tool to import results from a
model run back into HydraPlatform. It is recommended that the input data for
this GAMS model is generated using the GAMSexport plug-in. This is because
GAMSimport depends on a specific definition of the time axis and on the
presence of variables (attributes) in HydraPlatform that will hold the results
after import.


**Mandatory Arguments:**


====================== ====== ========== ======================================
Option                 Short  Parameter  Description
====================== ====== ========== ======================================
--network              -t     NETWORK    ID of the network where results will
                                         be imported to. Ideally this coincides
                                         with the network exported to GAMS.
--scenario            -s     SCENARIO    ID of the underlying scenario used for
--gams-model          -m     GMS_FILE    Full path to the GAMS model (*.gms)
                                         used for the simulation.
--gdx-file            -f     GDX_FILE   GDX file containing GAMS results


**Server-based arguments:**

====================== ====== ========== =========================================
Option                 Short  Parameter  Description
====================== ====== ========== =========================================
--server_url           -u     SERVER_URL Url of the server the plugin will
                                         connect to.
                                         Defaults to localhost.
--session_id           -c     SESSION_ID Session ID used by the calling software
                                         If left empty, the plugin will attempt
                                         to log in itself.

**Manually specifying the gams path:**

====================== ====== ========== ======================================
Option                 Short  Parameter  Description
====================== ====== ========== ======================================
--gams-path            -G     GAMS_PATH  File path of the GAMS installation.


GAMSimport needs a wrapper script that sets an environment variable
(``LD_LIBRARY_PATH``) before the gamsAPI library is loaded. This can not be
done at run-time because environment variables can not be set from a
running process.

Examples:
=========
hydra-gams import -t 4 -s 4 -f "/path/to/Results.gdx" -m "/path/to/Demo2.gms"


'''
from .importer import GAMSImporter, import_data
