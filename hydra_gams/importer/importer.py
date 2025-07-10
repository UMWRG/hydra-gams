# (c) Copyright 2013-2019 University of Manchester
import os
import sys
import re
import json
import copy

from decimal import Decimal
from operator import mul

from hydra_base.util.hydra_dateutil import ordinal_to_timestamp, date_to_string

from hydra_gams.lib import import_gms_data

from hydra_client.output import write_progress

import logging
log = logging.getLogger(__name__)

gdx=None


def import_data(network_id,
                   scenario_id,
                   gms_file,
                   gdx_file,
                   gams_path=None,
                   db_url=None,
                   connection=None):

    """
        Import results from a GDX file into a network
    """
    gdximport = GAMSImporter(scenario_id,
                             gms_file,
                             gdx_file,
#                             gams_path=gams_path,
                             db_url=db_url,
                             connection=connection)
    gdximport.import_data()

def get_gdx_files(filename):
    if filename is None:
        raise HydraPluginError("gdx file not specified.")
    from gams.core import gdx

    filename = os.path.abspath(filename)
    gdx_handle=gdx.new_gdxHandle_tp()
    gdx.gdxOpenRead(gdx_handle, filename)

    x, symbol_count, element_count = \
        gdx.gdxSystemInfo(gdx_handle)

    if x != 1:
        raise HydraPluginError('GDX file could not be opened.')

class GDXvariable(object):
    def __init__(self):
        self.name = None
        self.dim = 0
        self.records = 0
        self.description = None
        self.datatype = None
        self.data = []
        self.index = []

    def set_info(self, info, extinfo, var_domain=None):
        self.var_domain = var_domain
        if self.var_domain!=None:
            self.__get_domain()
        if info[1].endswith('_Pool_X'):
            self.name = info[1].replace('_Pool_X','')
        else:
            self.name = info[1]
        self.dim = info[2]
        self.records = extinfo[1]
        self.description = extinfo[3]

    def __get_domain(self):
        _domain=list(self.var_domain[1])
        if 'i' in _domain:
            _domain.remove('i')
        if 'j' in _domain:
            _domain.remove('j')
        # adding it as a string as Hydra accepts only a string for metdata value
        self.domain=json.dumps(_domain)

def get_index(index_file_names):
    from gams.core import gdx
    gdx_handle = gdx.new_gdxHandle_tp()
    rc = gdx.gdxCreate(gdx_handle, gdx.GMS_SSSIZE)
    gdx.gdxOpenRead(gdx_handle, index_file_names)
    x, symbol_count, element_count = \
        gdx.gdxSystemInfo(gdx_handle)
    for i in range(symbol_count):
        gdx_variable = GDXvariable()
        info = gdx.gdxSymbolInfo(gdx_handle, i + 1)
        extinfo = gdx.gdxSymbolInfoX(gdx_handle, i + 1)
        gdx_variable.set_info(info, extinfo)
        gdx.gdxDataReadStrStart(gdx_handle, i + 1)
        MGA_index = []
        for n in range(gdx_variable.records):
            x, idx, data, y = gdx.gdxDataReadStr(gdx_handle)
            MGA_index.append(idx[0])
        return MGA_index


class GAMSImporter:
    def __init__(self, scenario_id, gms_file, gdx_file, gams_path=None, connection=None, db_url=None, network=None):
        from gams.core import gdx
        self.gdx=gdx
        self.gdx_handle = gdx.new_gdxHandle_tp()
        log.info("1 =========================>"+str(self.gdx_handle))
        rc = gdx.gdxCreate(self.gdx_handle, gdx.GMS_SSSIZE)
        log.info("2 =============================>"+ str(rc))
        if rc[0] == 0:
            raise HydraPluginError('Could not find GAMS installation.')
        self.symbol_count = 0
        self.element_count = 0
        self.gdx_variables = dict()
        self.gams_units = dict()
        self.gdx_ts_vars = dict()

        self.steps       = 9
        self.current_step = 0

        self.network = network
        self.res_scenarios = []
        self.time_axis = dict()

        self.gms_file = gms_file
        self.gdx_file = gdx_file

        self.network_id=network.id if network is not None else None

        self.scenario_id = scenario_id
        self.template_id = None
        self.scenario = None

        self.gms_data = []

        self.connection = connection

        attrslist = self.connection.get_attributes()
        self.attrs = {attr.id:attr.name for attr in attrslist}

    def write_progress(self, step=None):
        """
            Utility function which automatically increments the current 'step'
            so as to avoid having to state it explicitly
            If 'step' is specified, it'll write that step.
        """

        if step is None:
            write_progress(self.current_step, self.steps)
            self.current_step = self.current_step+1
        else:
            write_progress(step, self.steps)

    def import_data(self):

        errors = []
        message = "Import successful."
        try:
            self.write_progress()

            self.load_network()
            self.write_progress()

            self.load_gams_file()
            self.write_progress()

            self.parse_time_index()
            self.write_progress()

            self.open_gdx_file()
            self.write_progress()

            self.read_gdx_data()
            self.write_progress()

            self.parse_variables('variables')
            self.parse_variables('positive variables')
            self.parse_variables('positive variable')
            self.parse_variables('binary variables')
            self.parse_variables('parameters')
            self.write_progress()

            self.assign_attr_data()
            self.write_progress()

            self.save()
            self.write_progress()

        except HydraPluginError as e:
            log.exception(e)
            errors = [e]
            message = "An error has occurred"
        except Exception as e:
            log.exception(e)
            errors = []
            message = "An unknown error has occurred"
            if e == '':
                if hasattr(e, 'strerror'):
                    errors = [e]
            else:
                errors = [e]

        self.write_progress(self.steps)

    def load_network(self, is_licensed=True):
        """
         Load network and scenario from the server. If the network
         has been set externally (to save getting it again) then simply
         set this.res_scenario using the existing network
        """

        # Use the network id specified by the user, if it is None, fall back to
        # the network id read from the gms file
        self.is_licensed = is_licensed

        if self.network:
            log.info("Not loading network as has been provided")
            return

        scenario_summary = self.connection.get_scenario(scenario_id=int(self.scenario_id),
                                                        include_data='N')
        self.network_id=scenario_summary.network_id

        try:
            scenario_id = int(self.scenario_id)
        except (TypeError, ValueError):
            pass
        if scenario_id is None:
            raise HydraPluginError("No scenario specified.")


        self.network = self.connection.get_network(network_id=int(self.network_id),
                                          template_id = self.template_id,
                                          scenario_ids = [self.scenario_id])

        if(is_licensed is False):
            if len(self.network.nodes)>20:
                raise HydraPluginError("The licence is limited demo (maximum limits are 20 nodes and 20 times steps).  Please contact software vendor (hydraplatform1@gmail.com) to get a full licence")

    #####################################################
    def set_network(self,is_licensed,  network):
        """
           Load network and scenario from the server.
        """
        self.is_licensed = is_licensed
        self.network = network
        if(is_licensed is False):
            if len(self.network.nodes)>20:
                raise HydraPluginError("The licence is limited demo (maximum limits are 20 nodes and 20 times steps).  Please contact software vendor (hydraplatform1@gmail.com) to get a full licence")
    #####################################################
    def get_mga_index(self, index_file_names):
        self.MGA_index=get_index(index_file_names)
        '''
        self.gdx.gdxOpenRead(self.gdx_handle, index_file_names)
        x, symbol_count, element_count = \
            self.gdx.gdxSystemInfo(self.gdx_handle)

        for i in range(symbol_count):
            gdx_variable = GDXvariable()
            info = self.gdx.gdxSymbolInfo(self.gdx_handle, i + 1)
            extinfo = self.gdx.gdxSymbolInfoX(self.gdx_handle, i + 1)
            gdx_variable.set_info(info, extinfo)
            self.gdx.gdxDataReadStrStart(self.gdx_handle, i + 1)
            self.MGA_index=[]
            for n in range(gdx_variable.records):
                x, idx, data, y = self.gdx.gdxDataReadStr(self.gdx_handle)
                self.MGA_index.append(idx[0])
        '''

    #####################################################
    def open_gdx_file(self):
        """
        Open the GDX file and read some basic information.
        """

        log.info("Reading GDX file")

        try:
            self.gdx_file = json.loads(self.gdx_file)
        except:
            pass

        if self.gdx_file is None:
            raise HydraPluginError("gdx file not specified.")

        if type(self.gdx_file) is list:
            self.is_MGA=True
            self.get_mga_index(os.path.expanduser(self.gdx_file[0]))
            self.gdx_file=os.path.expanduser(self.gdx_file[1])
        else:
            self.is_MGA = False
        #filename = os.path.abspath(filename)
        self.gdx.gdxOpenRead(self.gdx_handle, os.path.expanduser(self.gdx_file))

        x, self.symbol_count, self.element_count = \
            self.gdx.gdxSystemInfo(self.gdx_handle)
        if x != 1:
            raise HydraPluginError('GDX file could not be opened.')
        log.info('Importing %s symbols and %s elements.' %
                     (self.symbol_count, self.element_count))


    def read_gdx_data(self):
        """
           Read variables and data from GDX file.
        """

        log.info("Reading GDX Data")

        self.gdx.gdxOpenRead(self.gdx_handle, self.gdx_file)

        for i in range(self.symbol_count):
            gdx_variable = GDXvariable()

            info = self.gdx.gdxSymbolInfo(self.gdx_handle, i + 1)
            extinfo = self.gdx.gdxSymbolInfoX(self.gdx_handle, i + 1)
            var_domain = self.gdx.gdxSymbolGetDomainX(self.gdx_handle, i + 1)
            gdx_variable.set_info(info, extinfo, var_domain)
            self.gdx.gdxDataReadStrStart(self.gdx_handle, i + 1)

            for n in range(gdx_variable.records):
                x, idx, data, y = self.gdx.gdxDataReadStr(self.gdx_handle)
                gdx_variable.index.append(idx)
                gdx_variable.data.append(data[0])
            self.gdx_variables.update({gdx_variable.name: gdx_variable})


    def load_gams_file(self):
        """Read in the .gms file.
        """
        if self.gms_file is None:
            raise HydraPluginError(".gms file not specified.")

        gms_file = os.path.abspath(self.gms_file)

        gms_data = import_gms_data(gms_file)

        self.gms_data = gms_data.split('\n')

        if self.network_id is None or self.scenario_id is None:
            self.network_id, self.scenario_id = self.get_ids_from_gms()

    def get_ids_from_gms(self):
        """Read the network and scenario ids from the GMS file. This function
        should be called when the user doesn't supply a network and/or a
        scenario id.
        """
        # Get the very first line containing 'Network-ID' and 'Scenario-ID'
        networkline = next((x for x in self.gms_data if 'Network-ID' in x),
                           None)
        scenarioline = next((x for x in self.gms_data if 'Scenario-ID' in x),
                            None)
        if networkline is not None:
            network_id = int(networkline.split(':')[1])
        else:
            network_id = None

        if scenarioline is not None:
            scenario_id = int(scenarioline.split(':')[1])
        else:
            scenario_id = None

        return network_id, scenario_id

    def parse_time_index(self):
        """
        Read the time index of the GAMS model used. This only works for
        models where data is exported from Hydra using GAMSexport.
        """
        time_index_type=None
        for i, line in enumerate(self.gms_data):
            #if line[0:24] == 'Parameter timestamp(t) ;':
             #  break
            if line.strip().startswith('Parameter timestamp(yr, mn, dy)'):
                time_index_type='date'
                break
            elif line.strip().startswith('Parameter timestamp(t)'):
                time_index_type='t_index'
                break
        if time_index_type == "t_index":
            i += 2
            line = self.gms_data[i]
            while line.split('(', 1)[0].strip() == 'timestamp':
                idx = int(line.split('"')[1])
                timestamp = ordinal_to_timestamp(Decimal(line.split()[2]))
                timestamp = date_to_string(timestamp)
                self.time_axis.update({idx: timestamp})
                i += 1
                line = self.gms_data[i]
        elif time_index_type == "date":
           i += 2
           line = self.gms_data[i]
           while line.strip().startswith("timestamp"):
               line_parts=line.split("=")
               timestamp=ordinal_to_timestamp(Decimal(line_parts[1].replace(";","")))
               #idx=[timestamp.year, timestamp.month, timestamp.day]
               idx=str(timestamp.year)+"."+str(timestamp.month)+"."+str(timestamp.day)
               timestamp=date_to_string(timestamp)
               self.time_axis.update({idx: timestamp})
               i += 1
               line = self.gms_data[i]

        if(self.is_licensed is False):
            if len(self.time_axis)>20:
                raise HydraPluginError("The licence is limited demo (maximum limits are 20 nodes and 20 times steps).  Please contact software vendor (hydraplatform1@gmail.com) to get a full licence")

    def parse_variables(self, variable):
        """For all variables stored in the gdx file, check if these are time
        time series or not.
        """

        log.info("Parsing variables %s", variable)

        for i, line in enumerate(self.gms_data):
            if line.strip().lower() == variable:
                break

        i += 1
        if(i>=len(self.gms_data)):
            return

        line = self.gms_data[i]

        while line.strip() != ';':

            if len(line.strip()) == 0:
                break
            var = line.split()[0]
            splitvar = var.split('(', 1)
            if len(splitvar) <= 1:
                params = []
            else:
                params = splitvar[1][0:-1].split(',')
            varname = splitvar[0]
            if(re.search(r'\[(.*?)\]', line)!=None):
                self.gams_units.update({varname:
                                re.search(r'\[(.*?)\]', line).group(1)})
            else:
                error_message="Units are missing, units need to be added in square brackets where the variables are specified in the .gms file, ex: v1(i, t) my variable [m^3]"
            if 't' in params:
                self.gdx_ts_vars.update({varname: params.index('t')})
            elif('yr' in params and 'mn' in params and 'dy' in params):
                self.gdx_ts_vars.update({varname: params.index('dy')})
            i += 1
            line = self.gms_data[i]

    def assign_attr_data(self):
        """Assign data to all variable attributes in the network.
            """
        log.info("Assigning attribute data")

        if self.is_MGA == False:
            self.attr_data_for_single_sol()
        else:
            self.attr_data_for_MGA()

    def get_key(self, key_, table):
        for key in table:
            if key_.lower()==key.lower():
                return key
        return None

    def check_for_empty_values(selfself, values_):
        '''
        {"0": {}, "1": {}, "2": {}, "3": {}, "4": {}, "5": {}, "6": {}, "7": {}, "8": {}, "9": {}, "10": {}, "11": {}, "12": {}, "13": {}, "14": {}, "15": {}, "16": {}, "17": {}, "18": {}, "19": {}}
         '''
        valid=False
        for key in values_.keys():
            try:

                if len(values_[key])==0:
                    pass
                else:
                    return True
            except:
                return True
        return valid
    def attr_data_for_MGA (self):
        # Network attributes
        for attr in self.network.attributes:
            if attr.attr_is_var == 'Y':
                MGA_values = {}
                metadata = {}
                dataset = {'unit_id': None, 'locked': 'N'}
                _key =self.get_key(self.attrs[attr.attr_id] ,self.gdx_variables)
                if _key!=None:
                    for j in range(len(self.MGA_index)):

                        gdxvar = self.gdx_variables[_key]
                        dataset ['name']= gdxvar.name

                        # if (gdxvar.name in self.gams_units):
                        #     dataset['unit'] = self.gams_units[gdxvar.name]
                        # else:
                        #     dataset['unit'] = '-'
                        if gdxvar.name in self.gdx_ts_vars.keys():
                            dataset['type'] = 'timeseries'
                            index = []
                            count = 0
                            for idx in gdxvar.index:
                                if len(idx) == 2:
                                    index.append(idx[self.gdx_ts_vars[gdxvar.name]])
                                elif len(idx) == 3:
                                    index.append('.'.join(map(str, idx)))
                            data = gdxvar.data
                            MGA_values[j]= self.create_timeseries(index, data)

                        elif gdxvar.dim == 1:
                            if len(gdxvar.data) == 0:
                                MGA_values = {"0":{"0": 0}}
                                continue
                            data = gdxvar.data[j]
                            if not MGA_values:
                                MGA_values = {"0":{}}
                            try:
                                data_ = float(data)
                                MGA_values["0"][j] = data
                            except ValueError:
                                MGA_values["0"][j] = data
                        elif gdxvar.dim > 0 :
                            dataset['type'] = 'dataframe'
                            MGA_values.update(self.create_dataframe_from_mga_results(j, self.MGA_index[j], gdxvar.index, gdxvar.data))


                        # Add data
                if len(MGA_values)>0 and self.check_for_empty_values(MGA_values)==True:
                    dataset['value']=json.dumps(MGA_values)
                    dataset['type'] = 'dataframe'
                    metadata["sol_type"] = "MGA"
                    if gdxvar.var_domain!=None:
                        metadata['domain']=gdxvar.domain
                    dataset['metadata'] = json.dumps(metadata)
                    res_scen = dict(resource_attr_id=attr.id,
                                    attr_id=attr.attr_id,
                                    dataset=dataset)
                    self.res_scenarios.append(res_scen)
        # Node attributes
        nodes = dict()
        for node in self.network.nodes:
            nodes.update({node.id: node.name})
            for attr in node.attributes:
                if attr.attr_is_var == 'Y':
                    MGA_values = {}
                    metadata = {}
                    dataset = {'unit_id': None, 'locked': 'N'}

                    _key = self.get_key(self.attrs[attr.attr_id], self.gdx_variables)
                    if _key is not None:
                        for j in range(len(self.MGA_index)):
                            gdxvar = self.gdx_variables[_key]
                            dataset['name']= gdxvar.name

                            # if (gdxvar.name in self.gams_units):
                            #     dataset['unit'] = self.gams_units[gdxvar.name]
                            # else:
                            #     dataset['unit'] = '-'
                            if gdxvar.name in self.gdx_ts_vars.keys():
                                dataset['type'] = 'timeseries'
                                index = []
                                data = []
                                for i, idx in enumerate(gdxvar.index):
                                    if node.name in idx:
                                        if len(idx) == 4:
                                            index.append('.'.join(map(str, idx[1:])))
                                        elif len(idx) == 2:
                                            index.append(idx[self.gdx_ts_vars[gdxvar.name]])
                                        data.append(gdxvar.data[i])
                                #dataset['value'] = self.create_timeseries(index, data)
                                MGA_values[j]=self.create_timeseries(index, data)
                            elif gdxvar.dim == 2:
                                for i, idx in enumerate(gdxvar.index):
                                    if node.name in idx:
                                        data = gdxvar.data[i]
                                        try:
                                            data_ = float(data)
                                            dataset['type'] = 'scalar'
                                            MGA_values[j] = data
                                        except ValueError:
                                            dataset['type'] = 'descriptor'
                                            MGA_values[j] = data
                                        break

                            elif gdxvar.dim > 2:
                                index = []
                                data = []
                                MGA_values.update(self.create_dataframe_from_mga_results(j, self.MGA_index[j], gdxvar.index, gdxvar.data, node.name))
                                dataset['type'] = 'dataframe'

                    if len(MGA_values) > 0 and self.check_for_empty_values(MGA_values)==True:
                        metadata["sol_type"] = "MGA"
                        if gdxvar.var_domain != None:
                            metadata['domain'] = gdxvar.domain
                        dataset['value']=json.dumps(MGA_values)

                        dataset['type'] = 'dataframe'
                        dataset['metadata'] = json.dumps(metadata)
                        res_scen = dict(resource_attr_id=attr.id,
                                        attr_id=attr.attr_id,
                                        dataset=dataset)
                        self.res_scenarios.append(res_scen)
        # Link attributes
        for link in self.network.links:
            for attr in link.attributes:
                if attr.attr_is_var == 'Y':

                    MGA_values = {}
                    metadata = {}
                    dataset = {'unit_id': None, 'locked': 'N'}
                    _key =self.get_key(self.attrs[attr.attr_id] ,self.gdx_variables)
                    if _key!=None:
                        fromnode = nodes[link.node_1_id]
                        tonode = nodes[link.node_2_id]
                        for j in range(len(self.MGA_index)):
                            #dataset['value']=MGA_values
                            gdxvar = self.gdx_variables[self.attrs[attr.attr_id]]
                            dataset['name']=gdxvar.name
                            # if (gdxvar.name in self.gams_units):
                            #     dataset['unit'] = self.gams_units[gdxvar.name]
                            # else:
                            #     dataset['unit'] = '-'
                            if gdxvar.name in self.gdx_ts_vars.keys():
                                dataset['type'] = 'timeseries'
                                index = []
                                data = []
                                for i, idx in enumerate(gdxvar.index):
                                    if fromnode in idx and tonode in idx and \
                                                    idx.index(fromnode) < idx.index(tonode):
                                        if len(idx) == 5:
                                            index.append('.'.join(map(str, idx[2:])))
                                        elif len(idx) == 3:
                                            index.append(idx[self.gdx_ts_vars[gdxvar.name]])
                                        data.append(gdxvar.data[i])
                                MGA_values[j]=self.create_timeseries(index, data)
                                #dataset['value'] = self.create_timeseries(index, data)
                            elif gdxvar.dim == 2:
                                for i, idx in enumerate(gdxvar.index):
                                    if fromnode in idx and tonode in idx and \
                                                    idx.index(fromnode) < idx.index(tonode):
                                        data = gdxvar.data[i]
                                        try:
                                            data_ = float(data)
                                            dataset['type'] = 'scalar'
                                            MGA_values[j] = data
                                        except ValueError:
                                            dataset['type'] = 'descriptor'
                                            MGA_values[j] = (data)
                                        break
                            elif gdxvar.dim > 2:
                                is_in = False
                                if gdxvar.dim == 3:
                                    for i, idx in enumerate(gdxvar.index):
                                        if idx[0] == link.name and fromnode in idx and tonode in idx:
                                            data = gdxvar.data[i]
                                            try:
                                                data_ = float(data)
                                                dataset['type'] = 'scalar'
                                                MGA_values[j] = (data)
                                            except ValueError:
                                                dataset['type'] = 'descriptor'
                                                MGA_values[j] = (data)
                                            is_in = True
                                            break
                                if is_in is False:

                                    df = self.create_dataframe_from_mga_results(j, self.MGA_index[j], gdxvar.index, gdxvar.data, link.name)
                                    # continue
                                    MGA_values.update(df)

                                    if attr.name.lower() == 'al' and df:
                                        self.create_dataframe_from_mga_results(j, self.MGA_index[j], gdxvar.index, gdxvar.data, link.name)

                                    dataset['type'] = 'dataframe'

                    if len(MGA_values) > 0 and self.check_for_empty_values(MGA_values)==True:
                        dataset['value']=json.dumps(MGA_values)
                        dataset['type'] = 'dataframe'
                        metadata["sol_type"] = "MGA"
                        if gdxvar.var_domain != None:
                            metadata['domain'] = gdxvar.domain
                        dataset['metadata'] = json.dumps(metadata)
                        res_scen = dict(resource_attr_id=attr.id,
                                        attr_id=attr.attr_id,
                                        dataset=dataset)
                        self.res_scenarios.append(res_scen)

    def attr_data_for_single_sol(self):  # Network attributes

        for attr in self.network.attributes:
            if attr.attr_is_var == 'Y':
                if self.attrs[attr.attr_id] in self.gdx_variables.keys():
                    metadata = {}
                    gdxvar = self.gdx_variables[self.attrs[attr.attr_id]]
                    dataset = dict(name=gdxvar.name, unit_id=None, locked='N')
                    # if (gdxvar.name in self.gams_units):
                    #     dataset['unit'] = self.gams_units[gdxvar.name]
                    # else:
                    #     dataset['unit'] = '-'

                    if gdxvar.name in self.gdx_ts_vars.keys():
                        dataset['type'] = 'timeseries'
                        index = []
                        count = 0
                        for idx in gdxvar.index:
                            if len(idx) == 1:
                                index.append(idx[self.gdx_ts_vars[gdxvar.name]])
                            elif len(idx) == 3:
                                index.append('.'.join(map(str, idx)))
                        data = gdxvar.data
                        dataset['value'] = self.create_timeseries(index, data)
                    elif gdxvar.dim == 0:
                        data = gdxvar.data[0]
                        try:
                            data_ = float(data)
                            dataset['type'] = 'scalar'
                        except ValueError:
                            dataset['type'] = 'dataframe'

                        if data == {}:
                            continue

                        dataset['value'] = data
                    elif gdxvar.dim > 0:
                        continue
                        dataset['type'] = 'array'
                        dataset['value'] = self.create_array(gdxvar.index,
                                                             gdxvar.data)
                    # Add data
                    if dataset.get('value') is not None:
                        dataset['value']=dataset['value']
                        if gdxvar.var_domain != None:
                            metadata['domain'] = gdxvar.domain
                        dataset['metadata'] = json.dumps(metadata)
                        dataset['dimension'] = attr.resourcescenario.value.dimension
                        res_scen = dict(resource_attr_id=attr.id,
                                        attr_id=attr.attr_id,
                                        dataset=dataset)
                        self.res_scenarios.append(res_scen)
        # Node attributes
        nodes = dict()
        for node in self.network.nodes:
            nodes.update({node.id: node.name})
            for attr in node.attributes:
                if attr.attr_is_var == 'Y':
                    if self.attrs[attr.attr_id] in self.gdx_variables.keys():
                        metadata = {}
                        gdxvar = self.gdx_variables[self.attrs[attr.attr_id]]
                        dataset = dict(name=gdxvar.name, unit_id=None, locked='N')

                        # if (gdxvar.name in self.gams_units):
                        #     dataset['unit'] = self.gams_units[gdxvar.name]
                        # else:
                        #     dataset['unit'] = '-'
                        if gdxvar.name in self.gdx_ts_vars.keys():
                            dataset['type'] = 'timeseries'
                            index = []
                            data = []
                            for i, idx in enumerate(gdxvar.index):
                                if node.name in idx:
                                    if len(idx) == 4:
                                        index.append('.'.join(map(str, idx[1:])))
                                    elif len(idx) == 2:
                                        index.append(idx[self.gdx_ts_vars[gdxvar.name]])
                                    data.append(gdxvar.data[i])
                            dataset['value'] = self.create_timeseries(index, data)
                        elif gdxvar.dim == 1:
                            for i, idx in enumerate(gdxvar.index):
                                if node.name in idx:
                                    data = gdxvar.data[i]
                                    try:
                                        data_ = float(data)
                                        dataset['type'] = 'scalar'
                                        dataset['value'] = data
                                    except ValueError:
                                        dataset['type'] = 'descriptor'
                                        dataset['value'] = data
                                    break

                        elif gdxvar.dim > 1:
                            dataset['type'] = 'array'
                            index = []
                            data = []
                            inx = copy.deepcopy(gdxvar.index)
                            dat = copy.deepcopy(gdxvar.data)
                            for i, idx in enumerate(inx):
                                if node.name in idx:
                                    idx.pop(idx.index(node.name))
                                    index.append(idx)
                                    data.append(dat[i])

                            dataset['value'] = self.create_array(gdxvar.index, gdxvar.data, node.name)
                            dataset['type'] = 'dataframe'

                            if dataset['value'] == {}:
                                continue

                        if dataset.get('value') is not None:
                            dataset['value'] = dataset['value']
                            if gdxvar.var_domain != None:
                                metadata['domain'] = gdxvar.domain
                            dataset['metadata'] = json.dumps(metadata)

                            res_scen = dict(resource_attr_id=attr.id,
                                            attr_id=attr.attr_id,
                                            dataset=dataset)
                            self.res_scenarios.append(res_scen)

        # Link attributes
        for link in self.network.links:
            for attr in link.attributes:
                if attr.attr_is_var == 'Y':
                    fromnode = nodes[link.node_1_id]
                    tonode = nodes[link.node_2_id]
                    if self.attrs[attr.attr_id] in self.gdx_variables.keys():
                        metadata = {}
                        gdxvar = self.gdx_variables[self.attrs[attr.attr_id]]
                        dataset = dict(
                            name=gdxvar.name,
                            unit_id=None,
                            locked='N'
                        )
                        # if (gdxvar.name in self.gams_units):
                        #     dataset['unit'] = self.gams_units[gdxvar.name]
                        # else:
                        #     dataset['unit'] = '-'
                        if gdxvar.name in self.gdx_ts_vars.keys():
                            dataset['type'] = 'timeseries'
                            index = []
                            data = []
                            for i, idx in enumerate(gdxvar.index):
                                if fromnode in idx and tonode in idx and \
                                                idx.index(fromnode) < idx.index(tonode):
                                    if len(idx) == 5:
                                        index.append('.'.join(map(str, idx[2:])))
                                    elif len(idx) == 3:
                                        index.append(idx[self.gdx_ts_vars[gdxvar.name]])
                                    data.append(gdxvar.data[i])
                            dataset['value'] = self.create_timeseries(index, data)
                        elif gdxvar.dim == 2:
                            for i, idx in enumerate(gdxvar.index):
                                if fromnode in idx and tonode in idx and \
                                                idx.index(fromnode) < idx.index(tonode):
                                    data = gdxvar.data[i]
                                    try:
                                        data_ = float(data)
                                        dataset['type'] = 'scalar'
                                        dataset['value'] = data
                                    except ValueError:
                                        dataset['type'] = 'descriptor'
                                        dataset['value'] = data
                                    break
                        elif gdxvar.dim > 2:
                            is_in = False
                            if gdxvar.dim == 3:
                                for i, idx in enumerate(gdxvar.index):
                                    if idx[0] == link.name and fromnode in idx and tonode in idx:
                                        data = gdxvar.data[i]
                                        try:
                                            data_ = float(data)
                                            dataset['type'] = 'scalar'
                                            dataset['value'] = data
                                        except ValueError:
                                            dataset['type'] = 'descriptor'
                                            dataset['value'] = data
                                        is_in = True
                                        break
                            if is_in is False:
                                # continue
                                dataset['type'] = 'array'
                                '''
                                index = []
                                data = []
                                for i, idx in enumerate(gdxvar.index):
                                    if fromnode in idx and tonode in idx and \
                                       idx.index(fromnode) < idx.index(tonode):
                                        idx.pop(idx.index(fromnode))
                                        idx.pop(idx.index(tonode))
                                        index.append(idx)
                                        data.append(gdxvar.data[i])
                                '''
                                dataset['value'] = self.create_array(gdxvar.index,
                                                                     gdxvar.data, link.name)

                                # Should be removed later
                                dataset['type'] = 'dataframe'

                                if dataset['value'] == {}:
                                    continue

                        if dataset.get('value') is not None:
                            dataset['value'] = dataset['value']
                            if gdxvar.var_domain != None:
                                metadata['domain'] = gdxvar.domain
                            dataset['metadata'] = json.dumps(metadata)
                            res_scen = dict(resource_attr_id=attr.id,
                                            attr_id=attr.attr_id,
                                            dataset=dataset)
                            self.res_scenarios.append(res_scen)



    ########################################################################################
                            ################
    def create_dataframe_from_mga_results(self, idx, soln_, index, data, res):

        data = [round(d, 3) for d in data]
        elements = {}
        for i in range(0, len(index)):
            if(index[i][0]==soln_):
                if '_' in res and len(index[i]) == 5:
                    name = index[i][1] + "_" + index[i][2] + "_" + index[i][3]
                    if name == res:
                        key = index[i][4]
                        elements[idx] = {key : data[i]}
                        continue
                if '_' in res and len(index[i]) == 6:
                    name = index[i][1] + "_" + index[i][2] + "_" + index[i][3]
                    if name.lower() == res.lower():
                        if 'j_'+index[i][4].strip().lower() == index[i][2].strip().lower():
                            key = index[i][5]
                            elements[idx] = {key : data[i]}
                            continue
                        else:
                            key = index[i][5]
                            col = "%s.%s"%(index[i][4], idx)
                            if col in elements:
                                elements[col][key] = data[i]
                            else:
                                val = {key: data[i]}
                                elements[col] = val
                            continue
                    elif str(res).lower() == str(index[i][2] + "_" + index[i][3] + "_" + index[i][4]).lower():
                        if 'j_'+index[i][3].strip().lower() == index[i][1].strip().lower():
                            key = index[i][5]
                            elements[idx] = {key : data[i]}
                            continue
                        else:
                            key = index[i][5]
                            col = "%s"%(idx)
                            if col in elements:
                                elements[col][key] = data[i]
                            else:
                                val = {key: data[i]}
                                elements[col] = val
                            continue
                if len(index[i]) == 4 and index[i][3].strip().lower() == res.strip().lower():
                    col = "%s.%s" % (index[i][2], idx)
                    key = index[i][1]
                    if col in elements:
                        elements[col][key] = data[i]
                    else:
                        val = {key: data[i]}
                        elements[col] = val

                if len(index[i]) == 4 and index[i][1].strip().lower() == res.strip().lower():
                    col = "%s.%s" % (index[i][2], idx)
                    key = index[i][3]
                    if col in elements:
                        elements[col][key] = data[i]
                    else:
                        val = {key: data[i]}
                        elements[col] = val

                elif len(index[i]) == 3 and index[i][1].strip().lower() == res.strip().lower():
                    elements[idx] = {index[i][1]: data[i]}

        return elements
    #######################################################################################
    def create_array(self, index, data, res):

        data = [round(d, 3) for d in data]

        elements = {}
        for i in range(0, len(index)):
            if '_' in res and len(index[i]) == 4:
                 name = index[i][0] + "_" + index[i][1] + "_" + index[i][2]
                 if name == res:
                    key = index[i][3]
                    elements[key] = data[i]
                    continue
            if '_' in res and len(index[i]) == 5:
                name = index[i][0] + "_" + index[i][1] + "_" + index[i][2]
                if name == res:
                    key = index[i][4]
                    if key in elements:
                        elements[key][index[i][3]] = data[i]
                    else:
                        val = {index[i][3]: data[i]}
                        elements[key] = val
                    continue
            if len(index[i]) == 3 and index[i][2].strip().lower() == res.strip().lower():
                # ['2037-38', 'NYAA', 'norfolkrural']
                key = index[i][0]
                if key in elements:
                    elements[key][index[i][1]] = data[i]
                else:
                    val = {index[i][1]: data[i]}
                    elements[key] = val

                elements[index[i][0]] = (val)

            elif len(index[i]) == 2 and index[i][1].strip().lower() == res.strip().lower():
                val = {index[i][0]: data[i]}

                elements[index[i][0]] = (val)

                # elements[index[i][0]] = data[i]
        return (elements)

    def save(self):
        log.info("Saving")
        #first delete the old results
        # self.connection.delete_scenario_results(self.scenario_id)
        #Make this empty to avoid potential updates, and to save on work in Hydra
        self.connection.update_resourcedata(
            scenario_id=int(self.scenario_id),
            resource_scenarios=self.res_scenarios)
