#(c) Copyright 2013, 2014, 2015 University of Manchester\
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from shutil import copyfile
from dateutil import parser

import hydra_base
from hydra_base.exceptions import HydraPluginError
from hydra_client.output import write_progress, write_output, create_xml_response

from hydra_gams.lib import GamsModel
from hydra_gams import GAMSExporter, GAMSImporter

LOG = logging.getLogger(__name__)

def get_files_list(directory, ext):
    '''
    return list of files with specific ext on a folder with their last modified dates and times
    '''
    files_list = {}
    for file_ in os.listdir(directory):
        if file_.endswith(ext):
            absolute_path = os.stat(os.path.join(directory,file_))
            files_list[file_] = time.ctime(absolute_path.st_mtime)
    return files_list


def get_input_file_name(gams_model):
    '''
       Identify the name of the input file used by the model. if it is not provided by the user
    '''

    if os.path.isfile(os.path.expanduser(gams_model)) is False:
        raise HydraPluginError(f'Gams file {gams_model} not found.')

    inputfilename = None
    gamsfile = open(gams_model, "r")
    for line in gamsfile:
        if "include" not in line.lower():
            continue
        sline = line.strip()
        if len(sline) > 0 and sline[0].startswith('$'):
            lineparts = sline.split()
            if lineparts[1] == 'include':
                name = sline
                name = name.replace('$', '')
                name = name.replace('"', '')
                name = name.replace(';', '')
                name = name.replace('include', '')
                name = name.strip()
                inputfilename = os.path.join(os.path.dirname(gams_model),name)
                break
            elif lineparts[0] == '$include':
                name = sline
                name = name.replace('$', '')
                name = name.replace('"', '')
                name = name.replace(';', '')
                name = name.replace('include', '')
                name = name.strip()
                inputfilename=os.path.join(os.path.dirname(gams_model),name)
                break

    gamsfile.close()

    if inputfilename is None:
        raise HydraPluginError('Unable to identify the name of the input '
                               'file required by the model. '
                               'Please specify the name of the input filename.')

    inputfilepath = os.path.dirname(os.path.realpath(inputfilename))
    if os.path.exists(inputfilepath) is False:
        raise HydraPluginError(f'Output file directory {inputfilepath} does not exist.')

    LOG.info("Exporting data to: %s", inputfilename)

    return inputfilename

def register():
    base_plugin_dir = os.path.expanduser(hydra_base.config.get('plugin', 'default_directory'))
    gams_plugin_dir = os.path.join(base_plugin_dir, 'gams-app')
    app_dir = Path(os.path.join(gams_plugin_dir, 'run'))

    filename = 'plugin.xml'

    if not app_dir.exists():
        app_dir.mkdir(parents=True, exist_ok=True)

    app_path = os.path.dirname(os.path.expanduser(__file__))
    app_file = os.path.join(app_path, filename)

    target_path = Path(app_dir, filename)

    LOG.info("Copying from %s to %s", app_file, target_path)

    copyfile(app_file, target_path)

    LOG.info("GAMS Auto Run App Registered. ")

def run_gams_model(gms_file, debug=False, data_dir='/tmp'):
    """
        Run a gams model using the supplied GMS file.
    """
    LOG.info("Running GAMS model.")
    cur_time = datetime.now().replace(microsecond=0)
    working_directory = os.path.dirname(gms_file)
    if working_directory == '':
        working_directory = '.'

    model = GamsModel(working_directory, debug, data_dir=data_dir)
    model_job = model.add_job(gms_file)
    write_output("Running GAMS model, please note that this may take time")
    model.run()
    LOG.info("Running GAMS model finsihed")
    # if result file is not provided, it looks for it automatically at GAMS WD
    sol_pool = 'solnpool.gdx'
    res = 'results_MGA.gdx'

    LOG.info("Extracting results from %s.", working_directory)
    files_list = get_files_list(working_directory, '.gdx')
    if sol_pool in files_list:
        parsed_dt = parser.parse(files_list[sol_pool])
        parsed_dt_2 = parser.parse(files_list[res])
        delta = (parsed_dt - cur_time).total_seconds()
        delta_2 = (parsed_dt_2 - cur_time).total_seconds()
        # todo chaeck if dgx files exist
        if delta >= 0 and delta_2 >= 0:
            gdx_list = [os.path.join(working_directory, sol_pool),
                        os.path.join(working_directory, res)]

            gdx_file = gdx_list
            return gdx_file
        raise HydraPluginError(f'Tried looking for {sol_pool} and {res} created '
                               'since the model was run, but was '
                               'unable to find them.')
    else:
        for file_ in files_list:
            parsed_dt = parser.parse(files_list[file_])
            delta = (parsed_dt-cur_time).total_seconds()
            if delta >= 0:
                gdx_file = os.path.join(working_directory, file_)
        if gdx_file is None:
            raise HydraPluginError('Result file is not provided/found.')

        LOG.info("Results file: %s", gdx_file)

    return gdx_file

def export_run_import(client,
                      scenario_id,
                      gms_file,
                      template_id=None,
                      output=None,
                      node_node=None,
                      link_name=None,
                      start_date=None,
                      end_date=None,
                      time_step=None,
                      time_axis=None,
                      export_by_type=None,
                      gams_date_time_index=None,
                      debug=False,
                      default_dict = {},
                      settings_text='',
                      data_dir='/tmp'):
    """
        1. Export a hydra network to a GAMS input text file
        2. Run the specified model, using the newly created input file
        3. Import the results from the produced GDX file into the scenario specified.
    """
    try:
        steps = 18


        if output is None:
            output = get_input_file_name(gms_file)

        exporter = GAMSExporter(client,
                                scenario_id,
                                template_id,
                                output=output,
                                node_node=node_node,
                                link_name=link_name,
                                start_date=start_date,
                                end_date=end_date,
                                time_step=time_step,
                                time_axis=time_axis,
                                export_by_type=export_by_type,
                                gams_date_time_index=gams_date_time_index,
                                default_dict = default_dict,
                                settings_text=settings_text
                                )

        exporter.export()

        model_gdx_file = run_gams_model(gms_file, debug=debug, data_dir=data_dir)

        importer = GAMSImporter(scenario_id,
                                gms_file,
                                model_gdx_file,
                                network = exporter.hydranetwork,
                                connection=client)

        importer.import_data()

        message = "Run successfully"
        errors = []

    except HydraPluginError as e:
        LOG.exception(e)
        errors = [e]
        message = "An error has occurred"
    except Exception as e:
        errors = []
        if e == '':
            if hasattr(e, 'strerror'):
                errors = [e.strerror]
        else:
            errors = [e]
        LOG.exception(e)
        message = "An unknown error has occurred"

    write_progress(steps, steps)


#    if len(errors) > 0:#
        #raise Exception("An Error occurred running the Model. ")

    #text = create_xml_response('GAMSAuto', exporter.network.id, [scenario_id], message=message, errors=errors)

    #print(text)

    if len(errors) > 0:
        if hasattr(errors[0], 'message'):
            write_output(errors[0].message)
            sys.exit(errors[0].message)
        else:
            write_output(f"An error has occured:  {errors[0]}")
            sys.exit(errors[0])
