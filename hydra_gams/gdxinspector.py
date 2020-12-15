import gdxcc
import json
import os
import pandas as pd


def inspect(filename):

    full_filepath = os.path.expanduser(filename)
    gdx_handle = gdxcc.new_gdxHandle_tp()
    rc = gdxcc.gdxCreate(gdx_handle, gdxcc.GMS_SSSIZE)
    gdx = gdxcc.gdxOpenRead(gdx_handle, full_filepath)
    x, symbol_count, element_count = \
        gdxcc.gdxSystemInfo(gdx_handle)

    gdx_variables = {}

    for i in range(symbol_count):
        gdx_variable = GDXvariable()
        info = gdxcc.gdxSymbolInfo(gdx_handle, i + 1)
        extinfo = gdxcc.gdxSymbolInfoX(gdx_handle, i + 1)
        var_domain = gdxcc.gdxSymbolGetDomainX(gdx_handle, i + 1)
        gdx_variable.set_info(info, extinfo,var_domain)
        gdxcc.gdxDataReadStrStart(gdx_handle, i + 1)
        vardict = {}
        for n in range(gdx_variable.records):
            x, idx, data, y = gdxcc.gdxDataReadStr(gdx_handle)
            name = '_'.join(idx[1:-1])
            #the index contains both the option name and the data index, so we we need
            #to extract just the data index:
            #ex:['file1', 'bourne', 'j_Bourne_RuthamfordNorth_pot', 'ruthamfordnorth', 'DYAA', '2020-2021']
            #turns to ['2020-2021']
            data_idx = idx[-1]
            #for some reason the data has 4 trailing 0s, so delete them
            data = data[0]
            #data this small is error data
            if data < 0.01:
                continue

            if vardict.get(name) is None:
                vardict[name] = {data_idx : data}
            else:
                vardict[name][data_idx] = data

        gdx_variables[gdx_variable.name] = pd.DataFrame.from_dict(vardict).sort_index()


    years = gdx_variables['Q'].index
    print(f'years: {years}')

    import pudb; pudb.set_trace()

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
        if self.var_domain != None:
            self.__get_domain()
        if info[1].endswith('_Pool_X'):
            self.name = info[1].replace('_Pool_X', '')
        else:
            self.name = info[1]
        self.dim = info[2]
        self.records = extinfo[1]
        self.description = extinfo[3]

    def __get_domain(self):
        _domain = list(self.var_domain[1])
        if 'i' in _domain:
            _domain.remove('i')
        if 'j' in _domain:
            _domain.remove('j')
        if 'jun_set' in _domain:
            _domain.remove('jun_set')
        # adding it as a string as Hydra accepts only a string for metdata value
        self.domain = json.dumps(_domain)


