# (c) Copyright 2013, 2014, 2015 University of Manchester\

import os
import sys
import shutil
import logging

from hydra_client.resources import HydraResource, HydraNetwork
from hydra_base.exceptions import HydraPluginError

log = logging.getLogger(__name__)

#default for gams is 2, so no prefix required
python_version_prefix = ''

if (sys.version_info > (3, 0)):
     # Python 3 code in this block
     import base64
     python_version_prefix='_36'


class GamsModel(object):
    def __init__(self, working_directory, turn_debug_on, data_dir='/tmp'):
        gamspath=get_gams_path()
        self.working_directory = working_directory
        self.data_dir = data_dir
        log.info("Using GAMS Path: %s", gamspath)
        self.lst_name = '_gams_py_gjo0.lst'
        try:
            real_path = os.path.realpath(os.path.abspath(gamspath))
            api_path = os.path.join(real_path,'apifiles','Python','api'+python_version_prefix)
            if api_path not in sys.path:
                sys.path.insert(0, api_path)
            from gams import  workspace
            if turn_debug_on == True:
                debug_level = 3
            else:
                debug_level = 1
            self.ws = workspace.GamsWorkspace(working_directory=working_directory, system_directory=gamspath, debug = debug_level)

        except Exception as e:
            log.exception(e)
            raise HydraPluginError("Unable to import modules from gams. Please ensure that gams with version greater than 24.1 is installed.")

    def add_job(self, model_file):
       """
       read the model from the file and add model stratus scalar to the model
        and job to the Gams workspace
       """
       self.cp = self.ws.add_checkpoint()
       with open (model_file, "r") as myfile:
            model=myfile.read()
       self.model_name=self.get_model_name(model)
       if self.model_name is not None:
           self.model_name=self.model_name.replace(";", "")
           model=model+"\nscalar ms; \nms="+self.model_name.strip()+".Modelstat; "
           model = model + "\nscalar Sos; \nSos=" + self.model_name.strip() + ".Solvestat; "
           #model = model + "\nscalar TSos; \nTSos=" + self.model_name.strip() + ".Tsolstat; "

       self.job = self.ws.add_job_from_string(model)

    def get_model_name(self, model):
        '''
        get the model name from the GAMS model string
        '''
        lines=model.split("\n")
        for line in lines:
            line=line.lower()
            if line.startswith("model "):
                line=line.replace("model","")
                line=line.replace("/all/","")
                model_name=line.replace(";","").strip()
                line=line.split("/")
                if(line[0] is not None):
                    model_name=line[0]
                return model_name
        return None

    def get_dict(self, obj):
        if not hasattr(obj, "__dict__"):
            return obj
        result = {}
        for key, val in obj.__dict__.items():

           # if key.startswith("_"):
              #  continue
            if isinstance(val, list):
                element = []
                for item in val:
                    element.append(self.get_dict(item))
            else:
                element = self.get_dict(obj.__dict__[key])
            result[key] = element
        return result

    def check_model_status(self, status_key):
        error = None
        if (status_key == 4):
            error='Infeasible model found.'
        elif status_key == 5:
            error=('locally infeasible model found.')
        elif status_key == 6:
            error='Solver terminated early and model was still infeasible.'
        elif status_key == 7:
            error='Solver terminated early and model was feasible but not yet optimal.'
        elif status_key == 11:
            error='GAMS and/or solver licensing problem.'
        elif status_key == 12:
            error='Error - No cause known.'
        elif status_key == 13:
            error='Error - No solution attained.'
        elif status_key == 14:
            error='No solution returned.'
        elif status_key == 18:
            error='Unbounded - no solution.'
        elif status_key == 19:
            error='Infeasible - no solution.'
        return error

    def check_solver_status(self,s_status):
        error = None
        if(s_status== 2):
            error="Solver ran out of iterations"
        elif (s_status == 3):
            error="Solver exceeded time limit"
        elif (s_status == 4):
            error="Solver quit with a problem"
        elif (s_status == 5):
            error="Solver quit with nonlinear term evaluation errors"
        elif(s_status == 6):
            error="Solver terminated because the model is beyond the solvers capabilities"
        elif (s_status == 7):
            error="solver terminated with a license error"
        elif (s_status == 8):
            error="olver terminated on users request(e.g.Ctrl - C)"
        elif (s_status == 9):
            error="Solver terminated on setup error"
        elif (s_status == 10):
            error="Solver terminated with error"
        elif (s_status == 11):
            error="Solver terminated with error"
        elif (s_status == 12):
            error="Solve skipped"
        elif (s_status == 13):
            error="Other error"
        elif (s_status> 14):
            error="Undefined condition"
        return error


    def run(self):
        '''
        run the GAMS model
        and raise an error if something going wrong
        '''
        from gams import  workspace
        lst_location = os.path.join(self.working_directory, self.lst_name)
        try:
            self.job.run(checkpoint=self.cp)#, gams_options=options.ESol#print)
            if os.path.exists(lst_location):
                shutil.copyfile(lst_location, os.path.join(self.data_dir, self.lst_name))
        except workspace.GamsExceptionExecution as e:
            if os.path.exists(lst_location):
                shutil.copyfile(lst_location, os.path.join(self.data_dir, self.lst_name))

            if e.rc == 3:
                raise HydraPluginError("An exception occurred when executing the model. This is most likely caused by infeasibility.")
            elif e.rc == 2:
                raise HydraPluginError("There was a compilation error with the model. Please check the native output file for more details.")
            else:
                raise HydraPluginError("An unknown has occurred running the model. Please check the native output file for more details.")

        if self.model_name is not None:
            try:
                status=self.job.out_db["ms"].find_record().value
                s_status = self.job.out_db["Sos"].find_record().value
                #t_status=self.job.out_db["TSos"].find_record().value

            except:
                log.warn("Could not check solver and model termination status.")
                return

            log.warn("status: " + str(status))
            modelerror=self.check_model_status(status)
            solvererror=self.check_solver_status(s_status)
            if(modelerror is not None or solvererror is not None):
                raise HydraPluginError("Model error: "+str(modelerror)+"\nSolver error: "+str(solvererror))


class GAMSnetwork(HydraNetwork):
    def gams_names_for_links(self, use_link_name=False, jun=None):
        """
        Add a string to each link that can be used directly in GAMS code in
        order to define a link.
        """
        if use_link_name is False:
            for i, link in enumerate(self.links):
                if jun is None:
                    self.links[i].gams_name = link.from_node + ' . ' + link.to_node
                else:
                    self.links[i].gams_name = link.from_node + ' . ' + jun + ' . ' + link.to_node

        else:
            for i, link in enumerate(self.links):
                self.links[i].gams_name = link.name


class GAMSlink(HydraResource):
    gams_name = None
    from_node = None
    to_node = None


def convert_date_to_timeindex(date):
    totalseconds = date.hour * 3600 + date.minute * 60 + date.second
    return date.toordinal() + float(totalseconds) / 86400


def arr_to_matrix(arr, dim):
    """
    Reshape a multidimensional array to a 2 dimensional matrix.
    """
    tmp_arr = []
    for n in range(len(dim) - 2):
        for inner in arr:
            for i in inner:
                tmp_arr.append(i)
        arr = tmp_arr
        tmp_arr = []
    return arr


def create_arr_index(dim):
    arr_idx = []
    L = 1
    for d in dim:
        L *= d

    for l in range(L):
        arr_idx.append(())

    K = 1
    for d in dim:
        L = L / d
        n = 0
        for k in range(K):
            for i in range(d):
                for l in range(L):
                    arr_idx[n] += (i,)
                    n += 1
        K = K * d

    return arr_idx


def import_gms_data(filename):
    """
    Read whole .gms file and expand all $ include statements found.
    """
    if os.path.isfile(os.path.expanduser(filename))==False:
        raise HydraPluginError('Gams file '+filename+' not found.')

    basepath = os.path.dirname(filename)

    #print "gams files: "+filename
    gms_data = ''
    with open(filename) as f:
        while True:
            line = f.readline()
            if line == '':
                break
            sline = line.strip()
            if len(sline) > 0 and sline[0] == '$':
                lineparts = sline.split()
                #lineparts2 = sline.split("\"")

                if len(lineparts) > 2 and \
                        lineparts[1] == 'include':
                    ff=sline
                    ff=ff.replace('$','')
                    ff=ff.replace('"','')
                    ff=ff.replace(';','')
                    ff=ff.replace('include','')
                    ff=ff.strip()
                 ##   for ll in lineparts:
                     ##    #print ll
                     ####    if(ll.__contains__('include')|ll.__contains__('$')):
                        ##     continue

                    ##     ff=ff+ll

                    #line = import_gms_data(os.path.join(basepath, lineparts[2]))
                    line = import_gms_data(os.path.join(basepath, ff))
                elif len(lineparts) == 2 and lineparts[0] == '$include':
                    file__= os.path.join(basepath, lineparts[1])
                    if  os.path.isfile(file__):
                        line = import_gms_data(file__)
            gms_data += line
    return gms_data

def check_gams_installation():
    """
    Check that there is a valid, working GAMS installation. If the GAMS_PATH
    environmental variable is set, this is assumed to be true
    """
    gams_path = os.environ.get('GAMS_PATH')
    if(gams_path is None):
        gams_path = get_gams_path()
    try:
        real_path = os.path.realpath(os.path.abspath(gams_path))
        api_path = os.path.join(real_path,'apifiles','Python','api')
        if api_path not in sys.path:
            sys.path.insert(0, api_path)
            log.info ("real_path: "+ real_path)
        log.info("api_path: "+ api_path)

    except Exception as e:
        raise HydraPluginError("Unable to import modules from gams. Please ensure that gams with version greater than 24.1 is installed.")

def get_gams_path():
    """
	Attempt to determine the path to the local GAMS installation.
    First check whether it has been specified directly.
    If not, look in the most likely place for the gams installation given
    the operating system being used.
    This will only work with gams version 23.8 and above.
    """
    gams_path = os.getenv('GAMS_PATH')

    gams_python_api_path = None
    if gams_path is None:
        if os.name == 'nt':
            base = 'C://GAMS/'
            #Try looking in the default location.
            if os.path.exists(base):
                wintypes = [f for f in os.listdir(base) if f.find('win') >= 0]
                if len(wintypes) > 0:
                    gams_win_dir = base + wintypes[0] + '/'
                    gams_versions = [v for v in os.listdir(gams_win_dir)]
                    #Attempt to find the highest version by sorting the version
                    #directories and picking the last one
                    gams_versions.sort()
                    if len(gams_versions) > 0:
                        if float(gams_versions[-1]) < 24.1:
                                raise HydraPluginError("Only GAMS versions of 24.1 and above are supported automatically."
                                            " Please download the newest GAMS from (http://www.gams.com/download/) or "
                                            " specify the folder containing gams API using --gams-path")
                        else:
                            gams_path = gams_win_dir + gams_versions[-1]
        else:
            base = '/opt/gams/'
            #Try looking in the default location.
            if os.path.exists(base):
                linuxtypes = [f for f in os.listdir(base) if f.find('linux') >= 0]
                linuxtypes.sort()
                #Attempt to find the highest version by sorting the version
                #directories and picking the last one
                if len(linuxtypes) > 0:
                    gams_path = base + linuxtypes[-1]

        #try looking in the path
        if gams_path is None:
            path = os.environ['PATH']
            pathvars = path.split(':')
            for pathvar in pathvars:
                if pathvar.lower().find('gams') >= 0:
                    log.info('Found GAMS installation at %s', pathvar)
                    return pathvar

        if gams_path is not None:
            return gams_path
        else:
            raise HydraPluginError("Unable to find GAMS installation. Please specify folder containing gams executable.")
    else:
        return gams_path


key="12/FfCHspo*&s}:QMwd><s?:"
lic_file="gasm_l.bin"

lic_file=os.path.dirname(os.path.realpath(__file__))+"\\"+lic_file

REG_PATH="gams\lic"
#lic_file, REG_PATH, key

def check_lic():
    if os.name == 'nt':
        lic=License(lic_file, REG_PATH, key)
        return lic.is_licensed()
    else:
        return True
