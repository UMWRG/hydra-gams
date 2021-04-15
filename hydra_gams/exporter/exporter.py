# (c) Copyright 2013, 2014, 2015 University of Manchester\

import json
import logging
from decimal import Decimal
from string import ascii_lowercase

import pandas as pd

from hydra_base.exceptions import HydraPluginError
from hydra_base.util.hydra_dateutil import reindex_timeseries

from hydra_client.output import write_progress, write_output, create_xml_response

from hydra_gams.lib import GAMSnetwork, convert_date_to_timeindex

log = logging.getLogger(__name__)

def export_network(client,
                   scenario_id,
                   template_id,
                   output,
                   node_node,
                   link_name,
                   start_date,
                   end_date,
                   time_step,
                   time_axis,
                   export_by_type=False,
                   gams_date_time_index=False):

    """
        Export a network to a GAMS text input file.
    """
    message = None
    errors = []

    try:
        e = GAMSExporter(client,
                         scenario_id,
                         template_id,
                         output,
                         node_node,
                         link_name,
                         start_date,
                         end_date,
                         time_step,
                         time_axis,
                         export_by_type=export_by_type,
                         gams_date_time_index=gams_date_time_index)
        e.export()

    except HydraPluginError as e:
        write_progress(10, 10)
        log.exception(e)
        errors = [e]
    except Exception as e:
        write_progress(10, 10)
        log.exception(e)
        errors = []
        if e == '':
            if hasattr(e, 'strerror'):
                errors = [e]
        else:
            errors = [e]

    text = create_xml_response('GAMSExport',
                               e.hydranetwork.id,
                              [scenario_id],
                               errors = errors,
                               message=message)

    return exporter


class GAMSExporter:
    def __init__(self,
                 connection,
                 scenario_id,
                 template_id,
                 output,
                 node_node,
                 link_name,
                 start_date,
                 end_date,
                 time_step,
                 time_axis,
                 export_by_type=False,
                 gams_date_time_index=False,
                 default_dict = {},
                 settings_text=''):

        if template_id is not None:
            self.template_id = int(template_id)

        self.use_gams_date_index=False
        self.gams_date_time_index = gams_date_time_index
        self.export_by_type = export_by_type
        self.network_id = None
        self.scenario_id = int(scenario_id)
        self.template_id = int(template_id) if template_id is not None else None
        self.type_attr_default_datasets = {}
        ##default datasets, keyed on attribute name
        self.attr_default_datasets = {}
        self.filename = output
        self.time_index = []
        self.time_axis =None
        self.sets=""
        self.settings_text = settings_text ## put in some arbitrary settings
        ##this is a dictionary, keyed on attribute name.
        ##If a particular attribute is not contained in the input data, then it
        ##can be specified in this dict. Often used to ensure a model runs even when
        ##the hydra network may not contain some data required for it to run
        self.default_dict = default_dict ##
        self.steps = 7
        self.current_step=0
        self.node_types = []
        self.link_types = []
        self.group_types = []
        self.network_type = None


        #things which get written to the file without any logic (pre-formateed gams input text, or comments, for example
        self.direct_outputs = []

        self.descriptors = {}
        self.hashtables_keys={}
        self.output=''
        self.added_pars=[]
        self.junc_node={}
        self.link_code={}#Links are allowed to have 'codes' which are an attribute with a shorthand name to simplify indexing in the model
        self.empty_groups=[]
        #Keep track of all the groups which are subgroups (within other groups) as they are treated differently
        #to top-level groups. NOTE: This currently only supports 1 level of subgrouping
        self.subgroups = {}

        #Many groups have multiple indices. Empty groups must be exported with
        #the appropriate number of indices to avoid compilation errors. So we
        #must keep track of how many dimensions each group has (default is 1 unless
        #explicitly specified using the 'dimensions' attribute on the group type in the template.
        self.group_dimensions = {}

        self.connection = connection

        if time_axis is not None:
            time_axis = ' '.join(time_axis).split(' ')

        if(start_date is not None and end_date is not None and time_step is not None):
            self.time_axis = self.get_time_axis(start_date,
                                  end_date,
                                  time_step,
                                  time_axis=time_axis)
        if link_name is True:
            self.links_as_name = True
        else:
            self.links_as_name = False


        self.attrs = self.connection.get_attributes()
        self.attr_id_map = {}
        for a in self.attrs:
            self.attr_id_map[a.id] = a
        log.info("%s attributes retrieved", len(self.attrs))

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

    def export(self):
        """
            Export a network to a GAMS text input file.
        """
        write_output("Exporting Network")
        log.info("Exporting Network")
        self.write_progress()

        scenario_summary = self.connection.get_scenario(self.scenario_id, include_data=False)

        self.network_id=scenario_summary.network_id

        self.get_network()

        self.write_progress()
        if(self.gams_date_time_index is True):
            self.use_gams_date_index=True

        self.write_time_index()
        if self.export_by_type is True:
            self.export_data_using_types()
        else:
            self.export_data_using_attributes()

        self.write_progress()
        self.write_descriptors()

        self.write_progress()
        self.export_network()

        self.write_progress()
        self.write_file()

        write_output("Network exported successfully")
        log.info("Network exported successfully")

    def get_network(self):

        net = self.connection.get_network(network_id=self.network_id,
                                          include_data=True,
                                          include_results=False,
                                          template_id=self.template_id,
                                          scenario_ids=[self.scenario_id],
                                          include_metadata=True)

        self.hydranetwork=net
        log.info("Network retrieved")

        self.template_id = net.types[0].template_id
        self.template = self.connection.get_template(net.types[0].template_id)

        for t_type in self.template.templatetypes:
            self.type_attr_default_datasets[t_type.id] = {}
            for typeattr in t_type.typeattrs:
                attr_name = self.attr_id_map[typeattr.attr_id].name
                if typeattr.default_dataset is not None:
                    self.type_attr_default_datasets[t_type.id][attr_name] = typeattr.default_dataset
                    self.attr_default_datasets[typeattr.attr_id] = typeattr.default_dataset

        for templatetype in self.template.templatetypes:
            if templatetype.resource_type == 'NODE':
                self.node_types.append(templatetype)
            elif templatetype.resource_type == 'LINK':
                self.link_types.append(templatetype)
            elif templatetype.resource_type == 'GROUP':
                self.group_types.append(templatetype)
            elif templatetype.resource_type == 'NETWORK':
                self.network_type = templatetype

        log.info("Template retrieved")

        if net.scenarios is not None:
            for s in net.scenarios:
                if s.id == self.scenario_id:
                    self.scenario=s

        self.resourcescenarios_ids=get_resourcescenarios_ids(net.scenarios[0].resourcescenarios)

        self.network = GAMSnetwork()
        log.info("Loading net into gams network.")
        self.network.load(net, self.attrs)
        if (self.time_axis == None):
            s = net.scenarios[0]
            if (s.start_time is not None and s.end_time is not None and s.time_step is not None):
                self.time_axis = self.get_time_axis(net.scenarios[0]['start_time'],
                                               net.scenarios[0]['end_time'],
                                               net.scenarios[0]['time_step'],
                                               time_axis=None)
        if (self.time_axis is None):
            self.get_time_axis_from_attributes_values(self.network.nodes)
        if (self.time_axis is None):
            self.get_time_axis_from_attributes_values(self.network.links)

        #If links have a 'code' attirbute, build this dict
        #THis attribute is used for simpler modelling, rather than using start/end nodes to refer to a link
        self.get_link_codes()

        self.get_junc_link()
        if (len(self.junc_node) > 0):
            self.use_jun = True
        else:
            self.use_jun = False
        log.info("Gams network loaded")
        self.network.gams_names_for_links(use_link_name=self.links_as_name)
        log.info("Names for links retrieved")

        info = f"""* Data exported from Hydra using GAMSplugin.
* (c) Copyright 2015, University of Manchester
*
* {self.network.name}: {self.network.description}
* Network-ID:  {self.network.id}
* Scenario-ID: {self.network.scenario_id}
*******************************************************************************

"""

        settings_text =  f"*settings*\n{self.settings_text}\n\n*****************"
        self.sets += info + settings_text

    def check_links_between_nodes(self):
        for link in self.network.links:
            for link_ in self.network.links:
                if(link== link_):
                    continue
                if(link_.to_node==link.to_node and link_.from_node==link.from_node):
                    self.links_as_name = True
                    break

    def export_network(self):
        if self.links_as_name is False and len(self.junc_node)==0:
            self.check_links_between_nodes()

        #FIX ME: Export desriptors first as they don't rely on other entries, but others
        #may well rely on them.
        self.sets += '* Network definition\n\n'

        log.info("Exporting nodes")
        self.export_nodes()
        log.info("Exporting links")
        self.export_links()
        log.info("Exporting Groups")
        self.export_groups()


        log.info("Exporting groups that contain nodes")
        node_groups = self.export_node_groups()
        log.info("Exporting groups that contain links")
        link_groups = self.export_link_groups()
        #Do this here so we can identify which groups are subgroups, as they
        #must be handled differently
        log.info("Exporting subgroups")
        self.export_subgroups()
        log.info("Exporting groups that contain subgroups")
        subgroup_groups = self.export_subgroup_groups()

        #create groups that either have no elements or groups in the template
        #that are not in the network
        self.set_empty_groups(node_groups, link_groups, subgroup_groups)

        log.info("Creating connectivity matrix")
        #self.create_connectivity_matrix()
        log.info("Writing nodes coordinates")
        #self.export_resources_coordinates()
        log.info("Matrix created")

    def get_longest_node_link_name(self):
        node_name_len=0
        for node in self.network.nodes:
            if len(node.name)>node_name_len:
                node_name_len=len(node.name)

        self.name_len=str(node_name_len*2+5)
        self.array_len=str(node_name_len*2+15)

    def export_nodes(self):
        self.sets += 'SETS\n\n'
        # Write all nodes ...
        self.sets += 'i vector of all nodes /\n'
        for node in self.network.nodes:
            self.sets += node.name + '\n'
        self.sets += '    /\n\n'
        # ... and create an alias for the index i called j:
        self.sets += 'Alias(i,j)\n\n'
        # After an 'Alias; command another 'SETS' command is needed
        self.sets += '* Node types\n\n'
        self.sets += 'SETS\n\n'
        # Group nodes by type
        self.sets += 'nodes_types   /\n'
        for object_type in self.node_types:
            self.sets += object_type.name+'\n'
        self.sets += '/\n\n'

        for object_type in self.node_types:
            self.sets += object_type.name + '(i) /\n'
            for node in self.network.get_node(node_type_id=object_type.id):
                self.sets += node.name + '\n'
            self.sets += '/\n\n'

    def export_node_groups(self):
        "Export node groups if there are any."
        node_groups = []
        group_strings = []
        for group in self.network.groups:
            group_nodes = self.network.get_node(group=group.ID)
            if len(group_nodes) > 0:

                #is it a subgroup? If so, store it as such and don't write it
                #like a first-level group
                if group.name in self.subgroups:
                    for n in group_nodes:
                        self.subgroups[group.name]['contents'].append(n.name)

                node_groups.append(group)


                grp_str = ''
                grp_str += group.name + '(i) /\n'
                for node in group_nodes:
                    grp_str += node.name + '\n'
                grp_str += '/\n\n'
                group_strings.append(grp_str)

        if len(node_groups) > 0:
            self.sets += '* Node groups\n\n'
            self.sets += 'node_groups vector of all node groups /\n'
            for group in node_groups:
                self.sets += group.name + '\n'
            self.sets += '/\n\n'
            for grp_str in group_strings:
                self.sets += grp_str

        return node_groups


    def get_junc_link(self):
        for link in self.network.links:
            res=link.get_attribute(attr_name="jun_node")
            if res is None or res.value is None:
                  continue
            self.junc_node[link.name]=res.value

    def get_link_codes(self):
        for link in self.network.links:
            res=link.get_attribute(attr_name="code")
            if res is None or res.value is None:
                    continue
            self.link_code[link.name]=res.value

    def export_links(self):
        self.sets += 'SETS\n\n'
        # Write all links ...
        if self.links_as_name:
            self.sets += 'link_name /\n'
            for link in self.network.links:
                self.sets +=link.name+'\n'
            self.sets += '/\n\n'
            self.sets += 'links (link_name) vector of all links /\n'
        else:
            if self.use_jun==True:
                self.sets += 'links(i, jun_set, j) vector of all links /\n'
            else:
                self.sets += 'links(i,j) vector of all links /\n'
        for link in self.network.links:
            if self.links_as_name:
                self.sets += link.name +'\n'
            else:
                if(self.use_jun==True):
                    jun=self.junc_node[link.name]
                    self.sets += link.from_node+' . ' +jun+' . '+link.to_node+ '\n'
                else:
                    self.sets += link.gams_name + '\n'
        self.sets += '    /\n\n'
        # Group links by type
        self.sets += '* Link types\n\n'
        self.sets += 'links_types   /\n'
        for object_type in self.link_types:
            self.sets += object_type.name + '\n'
        self.sets += '/\n\n'

        for object_type in self.link_types:
            self.sets += object_type.name
            if self.links_as_name:
                self.sets +=  'link_name /\n'
            else:
                if self.use_jun == True:
                    self.sets += 'links(i, jun_set, j) vector of '+object_type.name+' links /\n'
                else:
                    self.sets += '(i,j) /\n'
            for link in self.network.get_link(link_type_id=object_type.id):
                if self.links_as_name:
                    self.sets += link.name + '\n'
                else:
                    if self.use_jun == True:
                        jun = self.junc_node[link.name]
                        self.sets += link.from_node + ' . ' + jun + ' . ' + link.to_node + '\n'
                    else:
                        self.sets += link.gams_name + '\n'
            self.sets += '/\n\n'

    def export_link_groups(self):
        "Export link groups if there are any."
        self.sets += '* Link groups ....\n\n'
        link_groups = []
        link_strings = []
        links_groups_members={}

        for group in self.network.groups:
            group_links = self.network.get_link(group=group.ID)
            if len(group_links) > 0:

                #is it a subgroup? If so, store it as such and don't write it
                #like a first-level group
                if group.name in self.subgroups:
                    manual_idx = group.get_attribute(attr_name='index')
                    if manual_idx is not None:
                        for l in group_links:
                            #If there's a 'Code' attribute, use that instead of the name.
                            if self.link_code.get(l.name):
                                ref_name = self.link_code[l.name]
                            else:
                                raise Exception("Group %s uses an index attribute '%s' but it is not found on link %s"%(group.name, manual_idx.name, l.name))
                            self.subgroups[group.name]['contents'].append(ref_name)
                            self.subgroups[group.name]['index'] = manual_idx.value
                    else:
                        for l in group_links:
                            self.subgroups[group.name]['contents'].append(l.gams_name)

                links_groups_members[group.name]=group_links
                link_groups.append(group)
                lstring = ''
                if self.links_as_name:
                    lstring +=  group.name+' /\n'
                else:
                    if self.use_jun == True:
                        lstring += group.name+ '(i, jun_set, j) vector links group /\n'
                    else:
                        lstring += '(i,j) /\n'
                for link in group_links:
                    if self.links_as_name:
                        lstring += link.name + '\n'
                    else:
                        if self.use_jun == True:
                            jun = self.junc_node[link.name]
                            lstring += link.from_node + ' . ' + jun + ' . ' + link.to_node + '\n'
                        else:
                            lstring += link.gams_name + '\n'
                    #lstring += link.gams_name + '\n'
                lstring += '/\n\n'
                link_strings.append(lstring)

        if len(link_groups) > 0:
            self.output += '\n* Link groups\n\n'
            for lstring in link_strings:
                self.sets += lstring

        return link_groups

    def export_groups(self):
        self.sets += 'SETS\n\n'
        # Write all groups ...
        self.sets += 'group_name /\n'
        for group in self.network.groups:
            self.sets +=group.name+'\n'
        self.sets += '/\n\n'
        self.sets += 'groups (group_name) vector of all groups /\n'
        for group in self.network.groups:
            self.sets += group.name +'\n'
        self.sets += '    /\n\n'
        # Group groups by type
        self.sets += '* group types\n\n'
        self.sets += 'group_types   /\n'
        for object_type in self.group_types:
            self.sets += object_type.name + '\n'
        self.sets += '/\n\n'

        for group in self.network.groups:
            group_subgroups=self.network.get_group(group=group.ID)
            if len(group_subgroups) > 0:
                #THis is a subgroup, so add to the list of subgroups for use when
                #exporting the node / link groups in case they are treated differently
                grouptype = group.get_type_by_template(self.template_id)
                for subgroup in group_subgroups:
                    subgrouptype = subgroup.get_type_by_template(self.template_id)
                    self.subgroups[subgroup.name] = {'parent': group.name,
                                                     'type':subgrouptype,
                                                     'parent_type': grouptype.name,
                                                     'contents':[],
                                                     'index':None}

        for object_type in self.group_types:
            groups_of_type = self.network.get_group(group_type_id=object_type.id)
            if len(groups_of_type) > 0 and groups_of_type[0].name not in self.subgroups:
                self.sets += object_type.name
                self.sets +=  ' /\n'
                for group in groups_of_type:
                    self.sets += group.name + '\n'
                self.sets += '/\n\n'


    def export_subgroup_groups(self):
        "Export subgroup groups if there are any."

        self.sets += '* Subgroup groups ....\n\n'

        subgroup_groups = []
        group_strings = []

        for group in self.network.groups:
            group_subgroups=self.network.get_group(group=group.ID)
            if len(group_subgroups) > 0:
                subgroup_groups.append(group)

                grp_str = ''
                grp_str += group.name + '(group_name) /\n'
                for subgroup in group_subgroups:
                    grp_str += subgroup.name + '\n'
                grp_str += '/\n\n'
                group_strings.append(grp_str)

        if len(subgroup_groups) > 0:
            self.sets += '* subgroup groups\n\n'
            self.sets += 'subgroup_groups vector of all subgroup groups /\n'
            for group in subgroup_groups:
                self.sets += group.name + '\n'
            self.sets += '/\n\n'
            for grp_str in group_strings:
                self.sets += grp_str

        return subgroup_groups

    def export_subgroups(self):

        self.sets += '* Subgroups ....\n\n'

        subgroup_sets = {}
        subgrouptype_parenttype_map = {}
        #Index by default is 'I' for nodes and 'I, J' for links.
        #But it can be other things such as 'I, jun_set, J' or 'Code', so need to keep track of it.
        subgroup_type_index = {}

        #Rearrange the data to put the group contents together, keyed on the subgroup type
        for subgroupname, subgroupdata in self.subgroups.items():
            parent_type=subgroupdata['parent_type']
            subgrouptype=subgroupdata['type']
            parent = subgroupdata['parent']

            subgrouptype_parenttype_map[subgrouptype.name] = parent_type

            contents = []
            for c in subgroupdata['contents']:
                contents.append((parent, c))

            if len(contents) == 0:
                #self.empty_groups.append(subgrouptype)
                log.info("Found an empty set %s. Adding to empty sets.", subgroupname)
                continue

            if subgroupdata.get('index') is not None:
                subgroup_type_index[subgrouptype.name] = subgroupdata['index']
            else:
                if contents[0][1].count('.') == 0:
                    subgroup_type_index[subgrouptype.name] = "I"
                else:
                    #Dependin on the number of dots, create an index i, j or i, j, k etc.
                    inum = ord('i')
                    idx = []
                    for i in range(contents[0][1].count('.')+1):
                        idx.append(chr(inum+i))
                    subgroup_type_index[subgrouptype.name] = ",".join(idx)

            if subgroup_sets.get(subgrouptype.name) is None:
                subgroup_sets[subgrouptype.name] = contents
            else:
                subgroup_sets[subgrouptype.name] = subgroup_sets[subgrouptype.name] + contents

        #Now that the data's in the correct format, #print it
        for subgrouptype_name, contents in subgroup_sets.items():
            parent_type = subgrouptype_parenttype_map[subgrouptype_name]
            index = subgroup_type_index[subgrouptype_name]
            self.sets += "%s (%s,%s)\n"%(subgrouptype_name, parent_type, index)
            self.sets += "/\n"
            for c in contents:
                self.sets += "%s . %s\n"%(c[0], c[1])

            self.sets += '/\n\n'

    def set_empty_groups(self, node_groups, link_groups, subgroup_groups):
        """
            Create a list of all the empty groups in the system so they can be exported as such.
            This includes group types for which there are no groups defined
        """

        non_empty_groups = node_groups + link_groups + subgroup_groups
        non_empty_group_IDS = [g.ID for g in non_empty_groups]
        non_empty_group_types = []
        #keep track of the group names to make sure that no empty groups with the same
        #name are added later. This is an edge case where the name of a group is the same
        #as a group type name, thus creating the possibility of duplicate group definitions in the input file
        group_names = []
        for group in self.network.groups:
            #if group.ID not in non_empty_group_IDS:
            #    self.empty_groups.append(group.get_type_by_template(self.template_id))
            group_names.append(group.name)
            non_empty_group_types.append(group.get_type_by_template(self.template_id).name)

        #Go through all group types and add empty sets for all those that don't
        #have a group set in the data
        for grouptype in self.group_types:
            self.group_dimensions[grouptype.name] = self.type_attr_default_datasets[grouptype.id].get('dimensions', {'value':1})['value']

            if grouptype.name not in non_empty_group_types and grouptype.name not in group_names:
                self.empty_groups.append(grouptype)

    def create_connectivity_matrix(self):
        ff='{0:<'+self.name_len+'}'

        self.output += '* Connectivity matrix.\n'
        self.output += 'Table Connect(i,j)\n'
        self.output +=ff.format('')
        node_names = [node.name for node in self.network.nodes]
        for name in node_names:
            self.output += ff.format( name)
        self.output += '\n'
        conn = [[0 for node in node_names] for node in node_names]
        for link in self.network.links:
            conn[node_names.index(link.from_node)]\
                [node_names.index(link.to_node)] = 1

        connlen = len(conn)
        rows = []
        for i in range(connlen):
            rows.append(ff.format( node_names[i]))
            txt = []
            for j in range(connlen):
                txt.append(ff.format( conn[i][j]))
            x = "".join(txt)
            rows.append("%s%s"%(x, '\n\n'))

        self.output = self.output + "".join(rows)

    def export_resources_coordinates(self):
        ff='{0:<'+self.name_len+'}'
        threeplaces = Decimal('0.001')
        self.output += ('\nParameter x_coord (i)/\n')

        for node in self.network.nodes:
            self.output += (ff.format(node.name))
            x_coord = Decimal(node.X).quantize(threeplaces)
            self.output += (ff.format(x_coord))
            self.output += ('\n')

        self.output += ('/;\n\nParameter y_coord (i)/\n')
        for node in self.network.nodes:
            self.output += (ff.format(node.name))
            y_coord = Decimal(node.Y).quantize(threeplaces)
            self.output += (ff.format(y_coord))
            self.output += ('\n')
        self.output += ('/;\n\n');

    def export_data_using_types(self):
        log.info("Exporting data")
        # Export node data for each node type
        data = ['* Node data\n\n']
        self.time_table={}
        for node_type in self.node_types:
            type_name = node_type.name
            data.append('* Data for node type %s\n\n' % type_name)
            nodes = self.network.get_node(node_type=type_name)
            data.extend(self.export_parameters_using_type(nodes, type_name, 'scalar'))
            data.extend(self.export_parameters_using_type(nodes, type_name, 'descriptor'))
            data.extend(self.export_timeseries_using_type(nodes, type_name))
            # data.extend(self.export_arrays(nodes))
            data.extend(self.export_hashtable(nodes))

        # Export link data for each node type
        data.append('* Link data\n\n')
        for link_type in self.link_types:
            type_name = link_type.name
            data.append('* Data for link type %s\n\n' % type_name)
            links = self.network.get_link(link_type=type_name)
            data.extend(self.export_parameters_using_type(links, type_name, 'scalar', res_type='LINK'))
            data.extend(self.export_parameters_using_type(links, type_name,'descriptor', res_type='LINK'))
            data.extend(self.export_timeseries_using_type(links, type_name, res_type='LINK'))
            #self.export_arrays(links)
            data.extend(self.export_hashtable(links))
        self.output = "%s%s"%(self.output, ''.join(data))
        log.info("Data exported")

    def export_data_using_attributes (self):
        log.info("Exporting data")
        # Export node data for each node
        self.get_longest_node_link_name()

        self.time_table={}
        data = ['\n* Network data\n']
        data.extend(self.export_parameters_using_attributes([self.network],'scalar',res_type='NETWORK'))
        self.export_descriptor_parameters_using_attributes([self.network])
        data.extend(self.export_hashtable([self.network],res_type='NETWORK'))

        data.append('\n\n\n* Nodes data\n')
        data.extend(self.export_parameters_using_attributes(self.network.nodes,'scalar'))
        self.export_descriptor_parameters_using_attributes(self.network.nodes)
        #data.extend(self.export_parameters_using_attributes (self.network.nodes,'descriptor'))
        data.extend(self.export_timeseries_using_attributes (self.network.nodes))
        #data.extend(self.export_arrays(self.network.nodes)) #?????
        data.extend(self.export_hashtable(self.network.nodes))

        # Export link data for each node
        data.append('\n\n\n* Links data\n')
        #links = self.network.get_link(link_type=link_type)
        data.extend(self.export_parameters_using_attributes (self.network.links,'scalar', res_type='LINK'))
        self.export_descriptor_parameters_using_attributes(self.network.links)
        #data.extend(self.export_parameters_using_attributes (self.network.links, 'descriptor', res_type='LINK'))
        data.extend(self.export_timeseries_using_attributes (self.network.links, res_type='LINK'))
        self.export_arrays(self.network.links) #??????
        data.extend(self.export_hashtable(self.network.links, res_type = 'LINK'))

        data.append('\n\n\n* Default data\n')
        data.extend(self.export_default_values())

        self.output = "%s%s"%(self.output, ''.join(data))
        log.info("Data exported")

    def export_parameters_using_type(self, resources, obj_type, datatype, res_type=None):
        """
        Export scalars or descriptors.
        """
        islink = res_type == 'LINK'
        attributes = []
        attr_names = []
        attr_outputs = []
        for resource in resources:
            for attr in resource.attributes:
                if attr.dataset_type == datatype and attr.is_var is False:
                    translated_attr_name = translate_attr_name(attr.name)
                    attr.name = translated_attr_name
                    if attr.name not in attr_names:
                        attributes.append(attr)
                        attr_names.append(attr.name)

        if len(attributes) > 0:
            attr_outputs.append('SETS\n\n')  # Needed before sets are defined

            attr_outputs.append(obj_type + '_' + datatype + 's /\n')

            for attribute in attributes:
                attr_outputs.append(attribute.name + '\n')

            attr_outputs.append('/\n\n')

            if islink:
                if self.links_as_name:
                    obj_index = 'i,links,j,'
                else:
                    if self.use_jun==True:
                        obj_index = 'i, jun_set, j,'
                    else:
                        obj_index = 'i,j,'
                attr_outputs.append('Table ' + obj_type + '_' + datatype + \
                    '_data(' + obj_index + obj_type + '_' + datatype + \
                    's) \n\n')
            else:
                attr_outputs.append('Table ' + obj_type + '_' + datatype + \
                    '_data(i,' + obj_type + '_' + datatype + 's) \n\n')

            attr_outputs.append('                        ')

            for attribute in attributes:
                attr_outputs.append(' %14s' % attribute.name)

            attr_outputs.append('\n')

            for resource in resources:
                if islink:
                    attr_outputs.append('{0:24}'.format(resource.gams_name))
                else:
                    attr_outputs.append('{0:24}'.format(resource.name))

                for attribute in attributes:
                    attr = resource.get_attribute(attr_name=attribute.name)

                    if attr is None or attr.value is None or attr.dataset_type != datatype:
                        continue

                    attr_outputs.append(' %14s' % attr.value)

                attr_outputs.append('\n')

            attr_outputs.append('\n\n')

        return attr_outputs

    def classify_attributes(self, resources,datatype ):
        for resource in resources:
            for resource2 in resources:
                if resource==resource2 or len(resource.attributes)!=len(resource2.attributes):
                    continue
                    isItId=True
                for attr in resource.attributes:
                    if isItId is False:
                        break
                    length=0
                    for attr2 in resource.attributes2:
                        if attr.name != attr2.name:
                            isItId=False
                            break
                        if length == len(resource2.attributes):
                            pass
                        else:
                            length += 1


    def export_parameters_using_attributes (self, resources, datatype, res_type=None):
            """Export scalars or descriptors.
            """
            islink = res_type == 'LINK'
            counter_=0
            attributes = []
            attr_names = []
            attr_outputs = []
            for resource in resources:
                for attr in resource.attributes:
                    if attr.dataset_type == datatype and attr.is_var is False:
                        translated_attr_name = translate_attr_name(attr.name)
                        res = resource.get_attribute(attr_name=attr.name)
                        attr.name = translated_attr_name
                        if attr.name not in attr_names:
                            attributes.append(attr)
                            attr_names.append(attr.name)

            ff='{0:<'+self.name_len+'}'
            if datatype=="descriptor":
                title="set"
            else:
                if res_type =='NETWORK':
                    title= "Scalar"
                else:
                    title="Parameter"

            for attribute in attributes:
                if islink == True:
                    if self.links_as_name:
                        attr_outputs.append('\n'+title+' '+ attribute.name+'(link_name)\n')
                    else:
                        if self.use_jun ==True:
                            attr_outputs.append('\n' + title + ' ' + attribute.name + '(i,jun_set,j)\n')
                        else:
                            attr_outputs.append('\n'+title+ ' '+ attribute.name+'(i,j)\n')
                elif(res_type is 'NETWORK'):
                    attr_outputs.append('\n'+title +' '+ attribute.name+'\n')
                else:
                    attr_outputs.append('\n'+title+' '+ attribute.name+'(i)\n')

                attr_outputs.append(ff.format('/'))
                #attr_outputs.append(ff.format(0))
                attr_outputs.append('\n')

                for resource in resources:
                    attr = resource.get_attribute(attr_name=attribute.name)

                    if attr is None or attr.value is None or attr.dataset_type != datatype:
                        continue
                    add = resource.name + "_" + attr.name
                    if add in self.added_pars:
                        continue
                    counter_+=1
                    if islink:
                        if self.links_as_name:
                            attr_outputs.append(ff.format(resource.name+ '.'+resource.from_node+'.'+resource.to_node))
                            attr_outputs.append(ff.format('\t'))
                        else:
                            if self.use_jun == True:
                                jun = self.junc_node[resource.name]
                                attr_outputs.append(ff.format(resource.from_node+' . '+jun+' . '+ resource.to_node))
                            else:
                                attr_outputs.append(ff.format(resource.gams_name))
                    elif(res_type is 'NETWORK'):
                         pass
                    else:
                        attr_outputs.append(ff.format(resource.name))

                    attr_outputs.append(ff.format(attr.value))
                    attr_outputs.append('\n')

                attr_outputs.append(ff.format('/;\n'))
            if(counter_>0):
                return attr_outputs
            else:
                return []

    def export_descriptor_parameters_using_attributes(self, resources):
        """Export scalars or descriptors.
        """
        datatype='descriptor'
        attributes = []
        attr_names = []
        attr_outputs = []
        for resource in resources:
            for attr in resource.attributes:
                if attr.dataset_type == datatype and attr.is_var is False:
                    translated_attr_name = translate_attr_name(attr.name)
                    attr.name = translated_attr_name
                    if attr.name not in attr_names:
                        attributes.append(attr)
                        attr_names.append(attr.name)
        for attribute in attributes:
            descriptor_list = []

            # attr_outputs.append(ff.format(0))
            attr_outputs.append('\n')

            for resource in resources:
                attr = resource.get_attribute(attr_name=attribute.name)

                if attr is None or attr.value is None or attr.dataset_type != datatype:
                    continue
                if attr.value not in descriptor_list:
                    descriptor_list.append(attr.value)


            if (len(descriptor_list) > 0):
                if len(descriptor_list) == 1:
                    self.direct_outputs.append(descriptor_list[0])
                else:
                    self.descriptors[attribute.name]=descriptor_list

    def export_timeseries_using_type(self, resources, obj_type, res_type=None):
        """Export time series.
        """
        islink = res_type == 'LINK'
        attributes = []
        attr_names = []
        attr_outputs = []

        #Identify only the timeseries values we're interested in.
        for resource in resources:
            for attr in resource.attributes:
                if attr.dataset_type == 'timeseries' and attr.is_var is False:
                    attr.name = translate_attr_name(attr.name)
                    if attr.name not in attr_names:
                        attributes.append(attr)
                        attr_names.append(attr.name)

        if len(attributes) > 0:
            attr_outputs.append('SETS\n\n')  # Needed before sets are defined
            attr_outputs.append(obj_type + '_timeseries /\n')
            for attribute in attributes:
                attr_outputs.append(attribute.name + '\n')
            attr_outputs.append('/\n\n')
            if islink:
                attr_outputs.append('Table ' + obj_type + \
                    '_timeseries_data(t,i,j,' + obj_type + \
                    '_timeseries) \n\n       ')
            else:

                attr_outputs.append('Table ' + obj_type + \
                    '_timeseries_data(t,i,' + obj_type + \
                    '_timeseries) \n\n       ')

            col_header_length = dict()
            for attribute in attributes:
                for resource in resources:
                    attr = resource.get_attribute(attr_name=attribute.name)
                    if attr is not None and attr.dataset_id is not None:
                        if islink:
                            col_header = ' %14s' % (resource.gams_name + '.'
                                                    + attribute.name)
                            col_header_length.update({(attribute, resource):
                                                      len(col_header)})
                            attr_outputs.append(col_header)
                        else:
                            col_header = ' %14s' % (resource.name + '.'
                                                    + attribute.name)
                            col_header_length.update({(attribute, resource):
                                                      len(col_header)})
                            attr_outputs.append(col_header)

            attr_outputs.append('\n')
            resource_data_cache = {}
            for timestamp in self.time_index:
                attr_outputs.append('{0:<7}'.format(self.times_table[timestamp]))

                for attribute in attributes:
                    for resource in resources:
                        attr = resource.get_attribute(attr_name=attribute.name)

                        #Only interested in attributes with data
                        if attr is None or attr.dataset_id is None:
                            continue

                        #Pass in the JSON value and the list of timestamps,
                        #Get back a dictionary with values, keyed on the timestamps
                        try:
                            all_data = resource_data_cache.get((resource.name, attribute.name))
                            if all_data is None:
                                all_data = self.get_time_value(attr.value, self.time_index)
                                resource_data_cache[(resource.name, attribute.name)] = all_data
                        except Exception as e:
                            log.exception(e)
                            all_data = None

                        if all_data is None:
                            raise HydraPluginError("Error finding value attribute %s on"
                                                  "resource %s"%(attr.name, resource.name))

                        #Get each value in turn and add it to the line
                        data = all_data[timestamp]

                        try:
                            data_str = ' %14f' % float(data)
                        except:
                            ff_='{0:<'+self.array_len+'}'
                            data_str = ff_.format(str(data))

                        attr_outputs.append(
                            data_str.rjust(col_header_length[(attribute, resource)]))

                attr_outputs.append('\n')
            attr_outputs.append('\n')
        return attr_outputs

    def get_time_axis_from_attributes_values(self, resources):
        attributes = []
        attr_names = []
        t_axis = []
        for resource in resources:
            for attr in resource.attributes:
                if attr.dataset_type == 'timeseries' and attr.is_var is False:
                    attr.name = translate_attr_name(attr.name)
                    if attr.name not in attr_names:
                        attributes.append(attr)
                        attr_names.append(attr.name)

        for attribute in attributes:
            for resource in resources:
                attr = resource.get_attribute(attr_name=attribute.name)
                if (attr != None):
                    vv = json.loads(attr.value)
                    for key in vv.keys():
                        for date in vv[key].keys():
                            if '9999' in date:
                                break
                            t_axis.append(date)
                if len(t_axis) > 0:
                    self.time_axis = self.get_time_axis(None,
                                                        None,
                                                        None,
                                                        time_axis=t_axis)
                    return

    def export_timeseries_using_attributes(self, resources, res_type=None):
            """Export time series.
            """
            islink = res_type == 'LINK'
            attributes = []
            attr_names = []
            attr_outputs = []
            counter_ = 0

            # Identify all the timeseries attributes and unique attribute
            # names
            for resource in resources:
                for attr in resource.attributes:
                    if attr.dataset_type == 'timeseries' and attr.is_var is False:
                        attr.name = translate_attr_name(attr.name)
                        if attr.name not in attr_names:
                            attributes.append(attr)
                            attr_names.append(attr.name)

            ff = '{0:<' + self.name_len + '}'
            t_ = ff.format('')

            for timestamp in self.time_index:
                t_ = t_ + ff.format(self.times_table[timestamp])

            for attribute in attributes:
                if(self.time_axis is None):
                    raise HydraPluginError("Missing time axis or start date, end date and time step or bad format")

                attr_outputs.append('\n*'+attribute.name)

                if islink:
                    if self.links_as_name:
                        attr_outputs.append('\nTable '+attribute.name + ' (link_name,i,j')
                    else:
                        attr_outputs.append('\nTable '+attribute.name + ' (i,j')
                else:
                    attr_outputs.append('\nTable '+attribute.name + ' (i')

                if self.use_gams_date_index is True:
                    attr_outputs.append(', yr, mn, dy)\n')
                else:
                    attr_outputs.append(', t)\n')

                if self.links_as_name:
                    attr_outputs.append('\n'+ff.format(''))
                    attr_outputs.append(str(t_))
                else:
                    attr_outputs.append('\n'+str(t_))

                #Identify the datasets that we need data for
                for resource in resources:
                    attr = resource.get_attribute(attr_name=attribute.name)

                    #Only interested in attributes with data and that are timeseries
                    if attr is None or attr.dataset_id is None or attr.dataset_type != "timeseries":
                        continue
                    add = resource.name + "_" + attr.name
                    if add in self.added_pars:
                        continue
                    counter_+=1

                    #Pass in the JSON value and the list of timestamps,
                    #Get back a dictionary with values, keyed on the timestamps
                    try:
                        all_data = self.get_time_value(attr.value, self.time_index)
                    except Exception as e:
                        log.exception(e)
                        all_data = None

                    if all_data is None:
                        raise HydraPluginError("Error finding value attribute %s on"
                                              "resource %s"%(attr.name, resource.name))
                    if islink:
                        if self.links_as_name:
                            attr_outputs.append('\n'+ff.format(resource.name+ '.'+resource.from_node+'.'+resource.to_node))
                            attr_outputs.append(ff.format('\t'))

                        else:
                            attr_outputs.append('\n'+ff.format(resource.gams_name))
                    else:
                        attr_outputs.append('\n'+ff.format(resource.name))

                    #Get each value in turn and add it to the line
                    for timestamp in self.time_index:
                        tmp = all_data[timestamp]

                        if isinstance(tmp, list):
                            data="-".join(tmp)
                            ff_='{0:<'+self.array_len+'}'
                            data_str = ff_.format(str(data))
                        else:
                            data=str(tmp)
                            data_str = ff.format(str(float(data)))
                        attr_outputs.append(data_str)

                attr_outputs.append('\n')

            attr_outputs.append('\n')
            if(counter_>0):
                return attr_outputs
            else:
                return []

    def export_default_values(self):
            """Export any values which have been set as default values in the template
            but which are not present in the network data.
            """
            attr_outputs = []
            if not self.default_dict:
                log.info("No default values to write")
                return attr_outputs

            used_attribute_names = []
            for resource in self.network.links:
                for attr in resource.attributes:
                    if attr.name not in used_attribute_names:
                        used_attribute_names.append(attr.name)
            for resource in self.network.nodes:
                for attr in resource.attributes:
                    if attr.attr_id not in used_attribute_names:
                        used_attribute_names.append(attr.name)

            values_to_write = set(self.default_dict) - set(used_attribute_names)

            for value_to_write in values_to_write:
                attr_outputs.append(self.default_dict[value_to_write])
                attr_outputs.append('\n')
            return attr_outputs


    def get_time_value(self, value, timestamps):
        '''
            get data for timmp

            :param a JSON string
            :param a timestamp or list of timestamps (datetimes)
            :returns a dictionary, keyed on the timestamps provided.
            return None if no data is found
        '''
        converted_ts = reindex_timeseries(value, timestamps)

        #For simplicity, turn this into a standard python dict with
        #no columns.
        value_dict = {}

        val_is_array = False
        if len(converted_ts.columns) > 1:
            val_is_array = True

        if val_is_array:
            for t in timestamps:
                value_dict[t] = converted_ts.loc[t].values.tolist()
        else:
            first_col = converted_ts.columns[0]
            for t in timestamps:
                value_dict[t] = converted_ts.loc[t][first_col]

        return value_dict

    def get_dim(self, arr):
        dim = []
        if type(arr) is list:
            for i in range(len(arr)):
                if type(arr[i]) is list:
                    dim.append((len(arr[i])))
                else:
                    dim.append(len(arr))
                    break
        else:
             dim.append(len(arr))
        return dim


    def compare_sets(self, key, key_):
        for item in key_:
            if not item in key:
                key.append(item)

        return key


    def export_hashtable(self, resources,res_type=None):
        """Export hashtable which includes seasonal data .
                    """
        islink = res_type == 'LINK'
        attributes = []
        attr_names = []
        attr_outputs = []
        id='default'
        ids={}
        ids_key={}
        data_types={}
        sets_namess={}
        # Identify all the timeseries attributes and unique attribute
        # names
        for resource in resources:
            for attr in resource.attributes:
                if attr.dataset_type in ('dataframe', 'array') and attr.is_var is False:
                    attr.name = translate_attr_name(attr.name)
                    if attr.name not in ids:
                       ids[attr.name] = {}
                    ids[attr.name][resource] = self.resourcescenarios_ids[attr.resource_attr_id]

                    if attr.name not in data_types:
                        metadata = self.resourcescenarios_ids[attr.resource_attr_id].value.metadata
                        log.debug(metadata)
                        if "type" in metadata:
                            data_types[attr.name]=metadata["type"].lower()
                        else:
                            data_types[attr.name]=self.resourcescenarios_ids[attr.resource_attr_id].type
                        if 'id' in metadata:
                            id_=metadata['id']
                             # "Found id and it -------------->", id_, attr.name
                            ids_key[attr.name]=id_
                    if attr.name not in sets_namess:
                        if "key" in metadata:
                            sets_namess[attr.name] = metadata["key"].lower()

                    if "sub_key" in metadata:
                        if attr.name+"_sub_key" not in sets_namess:
                            sets_namess[attr.name+"_sub_key"] = metadata["sub_key"].lower()

        for attribute_name in ids.keys():
            attr_outputs.append('\n\n\n*' + attribute_name)
            ff = '{0:<' + self.array_len + '}'
            t_ = ff.format('')
            counter=0
            type_= data_types[attribute_name]
            if attribute_name in sets_namess:
                set_name=sets_namess[attribute_name]
            else:
                set_name=attribute_name+"_index"
            if(type_ == "dataframe"):
                for resource, rs in ids[attribute_name].items():
                    add=resource.name+"_"+attribute_name
                    if add in self.added_pars:
                        continue
                    df = pd.read_json(rs.dataset.value)
                    if (set_name not in self.hashtables_keys):
                        self.hashtables_keys[set_name]=list(df.index)
                    else:
                        keys_=self.hashtables_keys[set_name]
                        self.hashtables_keys[set_name]=self.compare_sets(list(df.index), keys_)

                    for key in df.index:
                        t_ = t_ + ff.format(key)

                    if(counter ==0):
                        if islink == True:
                            if self.links_as_name:
                                attr_outputs.append('\n\nTable ' + attribute_name + ' (link_name, '+set_name+')')
                            else:
                                '''
                                id default is links start and end nodes and junction if have any
                                 if id is defined them it will be used to be the link id
                                '''
                                if attribute_name in ids_key:
                                    id=ids_key[attribute_name]
                                else:
                                    id= 'default'
                                if(id=='default'):
                                    if self.use_jun ==False:
                                        attr_outputs.append('\n\nTable ' + attribute_name + ' (i,j, '+set_name+')')
                                    else:
                                        attr_outputs.append('\n\nTable ' + attribute_name + ' (i,jun_set,j, ' + set_name + ')')
                                else:
                                    attr_outputs.append(
                                        '\n\nTable ' + attribute_name + ' ('+ id +', '+ set_name + ')')
                        elif res_type == "NETWORK":
                            attr_outputs.append('\n\nParameter '+ attribute_name + ' ('+ set_name + ')')

                        else:
                            attr_outputs.append('\n\nTable ' + attribute_name + ' (i, '+set_name+')')

                        if self.links_as_name:
                            attr_outputs.append('\n')# + ff.format(''))
                            attr_outputs.append(str(t_))
                        elif res_type != "NETWORK":
                            attr_outputs.append('\n' + str(t_))
                    counter+=1

                    if islink:
                        if self.links_as_name:
                            attr_outputs.append(
                                '\n' + ff.format(resource.name))
                            #attr_outputs.append(ff.format('\t'))

                        else:
                            if(id == 'default'):
                                if self.use_jun ==False:
                                    attr_outputs.append('\n' + ff.format(resource.from_node + '.' + resource.to_node))
                                else:
                                    jun = self.junc_node[resource.name]
                                    attr_outputs.append('\n' + ff.format(resource.from_node + '.' + jun+' . '+resource.to_node))
                            else:

                                id_value = resource.get_attribute(attr_name=id)
                                if id_value.value == None:
                                    break
                                attr_outputs.append('\n' + ff.format(id_value.value))

                    elif res_type == "NETWORK":
                        attr_outputs.append('\n' + ff.format('/')+'\n')

                    else:
                        attr_outputs.append('\n' + ff.format(resource.name))

                    for index in df.index:
                        for column in df.columns:
                            v = str(df[column][index])
                            if res_type != "NETWORK":
                                data_str = ff.format(v)
                                attr_outputs.append(data_str)
                            else:
                                ##print "=========>", data, attribute_name, "----------------------->"
                                data_str = ff.format(index)+ff.format(v)
                                attr_outputs.append(data_str+'\n')
            elif type_ =="hashtable_seasonal":
                for resource, rs in ids[attribute_name].items():
                    add=resource.name+"_"+attribute_name

                    if add in self.added_pars:
                        continue

                    df = pd.read_json(rs.dataset.value)

                    keys = df.index
                    if set_name not in self.hashtables_keys:
                        self.hashtables_keys[set_name] = keys

                    if attribute_name+"_sub_key" in sets_namess:
                        sub_set_name = sets_namess[attribute_name+"_sub_key" ]
                    else:
                        sub_set_name = attribute_name + "sub_set__index"

                    for key in df.columns:
                        t_ = t_ + ff.format(key)

                    if (counter == 0):
                        if islink:
                            if self.links_as_name:
                                attr_outputs.append(
                                    '\n\nTable ' + attribute_name + ' (link_name,' + set_name +','+sub_set_name+ ')')
                            else:
                                if self.use_jun==False:
                                    attr_outputs.append('\n\nTable ' + attribute_name + ' ('+set_name +', i,j, ' +sub_set_name+ ')')
                                else:
                                    attr_outputs.append(
                                        '\n\nTable ' + attribute_name + ' (' + set_name + ', i, jun_set, j, ' + sub_set_name + ')')
                        elif res_type == "NETWORK":
                            attr_outputs.append('\n\nTable ' + attribute_name + ' (' + set_name +','+sub_set_name+ ')')

                        else:
                            attr_outputs.append('\n\nTable ' + attribute_name + ' ('+set_name+', i, '+sub_set_name+ ')')
                        if self.links_as_name:
                            attr_outputs.append('\n' )#+ ff.format(''))
                            attr_outputs.append(str(t_))
                        elif res_type != "NETWORK":
                            attr_outputs.append('\n' + str(t_))
                    counter += 1
                    for key in df.index:
                        orig_key = key
                        key = str(key)
                        if islink == True:
                            if self.links_as_name:
                                attr_outputs.append(
                                    '\n' + ff.format(key+'.'+resource.name ))
                                attr_outputs.append(ff.format('\t'))

                            else:
                                if self.junc_node ==False:
                                    attr_outputs.append('\n' + ff.format(key+'.'+resource.from_node + '.' + resource.to_node))
                                else:
                                    jun = self.junc_node[resource.name]
                                    attr_outputs.append(
                                        '\n' + ff.format(key + '.' + resource.from_node + '.' +jun+ '.' + resource.to_node))

                        elif res_type == "NETWORK":
                            attr_outputs.append('\n' + ff.format(key) + '\n')

                        else:
                            attr_outputs.append('\n' + ff.format(key+'.'+resource.name))

                        if sub_set_name not in self.hashtables_keys:
                            self.hashtables_keys[sub_set_name] = df.columns

                        for col in df.columns:
                            if res_type != "NETWORK":
                                data_str = ff.format(str((df[col][orig_key])))
                                attr_outputs.append(data_str)
                            else:
                                data_str = ff.format(keys[i]) + ff.format(str(float(df[col][orig_key])))
                                attr_outputs.append(data_str + '\n')

            elif type_ == "nodes_array_collection" and res_type == "NETWORK":
                for resource, rs in ids[attribute_name].items():
                    value_ = json.loads(rs.dataset.value)
                    keys = value_
                    #this is where the EBSD 'yr' table gets created.
                    attr_outputs.extend(self.get_resourcess_array_pars_collection(self.network.nodes, attribute_name, keys, set_name))
                    if (set_name not in self.hashtables_keys):
                        self.hashtables_keys[set_name] = keys
                    else:
                        keys_ = self.hashtables_keys[set_name]
                        self.hashtables_keys[set_name] = self.compare_sets(keys, keys_)

            elif type_ == "links_array_collection" and res_type == "NETWORK":
                for resource, rs in ids[attribute_name].items():
                    value_ = json.loads(rs.dataset.value)
                    keys = value_
                    attr_outputs.extend(self.get_resourcess_array_pars_collection(self.network.links, attribute_name, keys, set_name, True))
                    if (set_name not in self.hashtables_keys):
                        self.hashtables_keys[set_name] = keys
                    else:
                        keys_ = self.hashtables_keys[set_name]
                        self.hashtables_keys[set_name] = self.compare_sets(keys, keys_)
            elif type_ == "nodes_scalar_collection" and res_type == "NETWORK":
                for resource, rs in ids[attribute_name].items():
                    value_ = json.loads(rs.dataset.value)
                    keys = value_
                    attr_outputs.extend(self.get_resourcess_scalar_pars_collection(self.network.nodes, attribute_name, keys, set_name))
                    if (set_name not in self.hashtables_keys):
                        self.hashtables_keys[set_name] = keys
                    else:
                        keys_ = self.hashtables_keys[set_name]
                        self.hashtables_keys[set_name] = self.compare_sets(keys, keys_)
            elif type_ == "links_scalar_collection" and res_type == "NETWORK":
                for resource, rs in ids[attribute_name].items():
                    value_ = json.loads(rs.dataset.value)
                    keys = value_
                    attr_outputs.extend(self.get_resourcess_scalar_pars_collection(self.network.links, attribute_name, keys, set_name, True))
                    if (set_name not in self.hashtables_keys):
                        self.hashtables_keys[set_name] = keys
                    else:
                        keys_ = self.hashtables_keys[set_name]
                        self.hashtables_keys[set_name] = self.compare_sets(keys, keys_)

            elif type_ == "links_set_collection" and res_type == "NETWORK":
                for resource, rs in ids[attribute_name].items():
                    value_ = json.loads(rs.dataset.value)
                    keys = value_
                    if attribute_name in ids_key:
                        id=ids_key[attribute_name]
                    else:
                        id='default'

                    attr_outputs.extend(
                        self.get_resourcess_set_collection(self.network.links, attribute_name, keys,id,
                                                                   True))
            elif type_ == "set_collection" and res_type == "NETWORK":
                for resource, rs in ids[attribute_name].items():
                    value_ = json.loads(rs.dataset.value)
                    keys = value_
                    if attribute_name not in self.hashtables_keys:
                        self.hashtables_keys[attribute_name]=keys


            if res_type == "NETWORK":
                attr_outputs.append('/;')
        return attr_outputs


    def is_it_in_list(self, item, list):
        for item_ in list:
            if item.lower().strip() == item_.lower().strip():
                return True
        return False

    def get_resourcess_array_pars_collection(self, resources, attribute_name_, pars_collections, set_name_, islink=False):
        attributes = []
        attr_names = []
        attr_outputs = []
        ids = {}
        data_types = {}
        sets_namess = {}
        # Identify all the timeseries attributes and unique attribute
        # names
        main_key=''
        sub_key=''
        for resource in resources:
            for attr in resource.attributes:
                if attr.dataset_type == 'dataframe' and attr.is_var is False and self.is_it_in_list(attr.name, pars_collections)==True:
                    attr.name = translate_attr_name(attr.name)
                    if attr.name not in ids:
                       ids[attr.name] = {}
                    ids[attr.name][resource] = self.resourcescenarios_ids[attr.resource_attr_id]

                    if attr.name not in data_types:
                        type_ = self.resourcescenarios_ids[attr.resource_attr_id].value.metadata
                        if "type" in type_:
                            data_types[attr.name] = type_["type"].lower()
                        else:
                            data_types[attr.name]=self.resourcescenarios_ids[attr.resource_attr_id].type
                    if attr.name not in sets_namess:
                        if "key" in type_:
                            sets_namess[attr.name] = type_["key"].lower()
                            main_key= type_["key"].lower()
                    if "sub_key" in type_:
                        if attr.name + "_sub_key" not in sets_namess:
                            sets_namess[attr.name + "_sub_key"] = type_["sub_key"].lower()
                            sub_key=type_["sub_key"].lower()
        if islink ==True:
            res_type='link'
        else:
            res_type='node'
        counter=0
        for attribute_name in ids.keys():
            attr_outputs.append('*' + attribute_name)
            ff = '{0:<' + self.array_len + '}'
            type_ = data_types[attribute_name]
            if attribute_name in sets_namess:
                set_name = sets_namess[attribute_name]
            else:
                set_name = attribute_name + "_index"
            if (type_ == "dataframe"):
                if counter==0:
                    if (islink == False):
                        attr_outputs.append(
                            'Parameter ' + attribute_name_ + ' (i,' + set_name_ + ', ' + main_key + ')')
                    else:
                        if self.links_as_name:
                            attr_outputs.append(
                                'Parameter ' + attribute_name_ + ' (link_name,' + set_name_ + ', ' + main_key + ')')
                        else:
                            if self.use_jun:
                                jun = self.junc_node[resource.name]
                                attr_outputs.append(
                                    'Parameter ' + attribute_name_ + ' (i, jun_set, j, ' + set_name_ + ',' + main_key + ')')
                            else:
                                attr_outputs.append(
                                    'Parameter ' + attribute_name_ + ' (i, j, ' + set_name_ + ',' + main_key + ')')
                    attr_outputs.append('/')
                for resource, rs in ids[attribute_name].items():
                    add = resource.name + "_" + attribute_name
                    if not add in self.added_pars:
                        self.added_pars.append(add)

                    df = pd.read_json(rs.dataset.value)
                    #setting the 'yr' here.
                    if (set_name not in self.hashtables_keys):
                        self.hashtables_keys[set_name] = list(df.index)
                    else:
                        keys_ = self.hashtables_keys[set_name]
                        self.hashtables_keys[set_name] = self.compare_sets(list(df.index), keys_)

                    for index in df.index:
                        for column in df.columns:
                            data_str = ff.format(str(df[column][index]))
                            if islink == True:
                                if self.links_as_name:
                                    attr_outputs.append(
                                        resource.name+' . '+ attribute_name+index + ' . ' + '   ' + data_str)
                                else:
                                    if self.use_jun == False:
                                        attr_outputs.append(resource.from_node + ' . ' + resource.to_node+' . '+ attribute_name +index + '  ' +data_str)
                                    else:
                                        jun = self.junc_node[resource.name]
                                        attr_outputs.append(
                                            resource.from_node + ' . ' + jun+' . '+resource.to_node + ' . ' + attribute_name + ' . '+index + '  ' + data_str)
                            else:
                                attr_outputs.append(resource.name+ ' . ' + attribute_name+' . '+ str(index) + '   ' + data_str)
                counter+=1
            elif type_ == "hashtable_seasonal":
                if counter==0:
                    if (islink == False):
                        attr_outputs.append(
                            'Parameter ' + attribute_name_ + ' (' + main_key + ', ' + sub_key + ', ' + set_name_ + ', i)')
                    else:
                        if self.links_as_name == True:
                            attr_outputs.append(
                                'Parameter ' + attribute_name_ + ' (' + main_key + ', ' + sub_key + ',' + set_name_ + ', link_name)')
                        else:
                            if self.use_jun == False:
                                attr_outputs.append('Parameter ' + attribute_name_ + ' (' + main_key + ', ' + sub_key + ',' + set_name_ + ', i, j)')
                            else:
                                attr_outputs.append('Parameter ' + attribute_name_ + ' (' + main_key + ', ' + sub_key + ',' + set_name_ + ', i, jun_set, j)')

                    attr_outputs.append('/')
                for resource, rs in ids[attribute_name].items():
                    add = resource.name + "_" + attribute_name
                    if not add in self.added_pars:
                        self.added_pars.append(add)

                    df = pd.read_json(rs.dataset.value)

                    if set_name not in self.hashtables_keys:
                        self.hashtables_keys[set_name] = list(df.index)

                    for index in df.index:
                        for column in df.columns:
                            v = str(df[column][index])
                            if islink:
                                if self.links_as_name:
                                    attr_outputs.append(
                                         (index + ' . ' + column +' . '+ attribute_name+ ' . ' +resource.name+'    ' + v ))
                                else:
                                    if self.use_jun == False:
                                        attr_outputs.append((index + ' . ' + column + ' . ' + attribute_name + ' . ' + resource.from_node + '.' + resource.to_node + '    ' + v))
                                    else:
                                        jun = self.junc_node[resource.name]
                                        attr_outputs.append((index + ' . ' + column + ' . ' + attribute_name + ' . ' + resource.from_node + '.' + jun+'.'+resource.to_node + '    ' + v))

                            else:
                                attr_outputs.append(
                                    (str(index) + ' . ' + column + ' . ' + attribute_name + ' . ' + resource.name + '    ' + v))
                counter += 1
        #attr_outputs.append('/;')
        #ss='\n'.join(attr_outputs)
        #with open("c:\\temp\\"+attribute_name_+".txt", 'w') as f:
        #    f.write(ss)
        return '\n'.join(attr_outputs)

    def get_resourcess_scalar_pars_collection(self, resources, attribute_name_, pars_collections, set_name_,
                                             islink=False):
        attributes = []
        attr_names = []
        attr_outputs = []
        ids = {}
        data_types = {}
        sets_namess = {}
        if islink == True:
            res_type = 'link'
        else:
            res_type = 'node'
        # Identify all the timeseries attributes and unique attribute
        # names
        for resource in resources:
            for attr in resource.attributes:
                if attr.dataset_type == 'scalar' and attr.is_var is False and self.is_it_in_list(attr.name,
                                                                                                pars_collections) == True:
                    attr.name = translate_attr_name(attr.name)
                    if attr.name not in ids:
                       ids[attr.name] = {}
                    ids[attr.name][resource] = self.resourcescenarios_ids[attr.resource_attr_id]

        counter = 0
        for attribute_name in ids:
            attr_outputs.append('*' + attribute_name)
            ff = '{0:<' + self.array_len + '}'
            if counter == 0:
                if (islink == True):
                    if self.links_as_name:
                        attr_outputs.append('Parameter ' + attribute_name_ + ' (' + set_name_ + ')')
                    else:
                        if self.use_jun == False:
                            attr_outputs.append('Parameter ' + attribute_name_ + ' (i, j, ' + set_name_ +  ')')
                        else:
                            attr_outputs.append('Parameter ' + attribute_name_ + ' (i, jun_set, j, ' + set_name_ + ')')
                else:
                    attr_outputs.append(
                        'Parameter ' + attribute_name_ + ' (i,' + set_name_ + ')')
                attr_outputs.append('/')
            for resource, rs in ids[attribute_name].items():
                add = resource.name + "_" + attribute_name
                if not add in self.added_pars:
                    self.added_pars.append(add)
                value_ = (rs.dataset.value)
                if islink:
                    if self.links_as_name:
                        attr_outputs.append(
                            resource.name + ' . ' + attribute_name + '   ' + value_)
                    else:
                        if self.use_jun == False:
                            attr_outputs.append(resource.from_node + ' . ' + resource.to_node + ' . ' + attribute_name + '  ' + value_)
                        else:
                            jun = self.junc_node[resource.name]
                            attr_outputs.append(
                                resource.from_node + ' . '+jun+' . ' + resource.to_node + ' . ' + attribute_name + '  ' + value_)

                else:
                    attr_outputs.append(resource.name + ' . ' + attribute_name +  '   ' + value_)
            counter += 1
        #attr_outputs.append('/;')
        #ss = '\n'.join(attr_outputs)
        #with open("c:\\temp\\" + attribute_name_ + ".txt", 'w') as f:
        #    f.write(ss)
        return '\n'.join(attr_outputs)


    ###########################
    def get_resourcess_set_collection(self, resources, set_title_, set_collections, id,
                                      islink=False):

        attr_outputs = []
        ids = {}

        if islink == True:
            res_type = 'link'
        else:
            res_type = 'node'
        title=''
        if id == 'default':
            if (islink == True):
                if self.links_as_name:
                    title='set ' + set_title_ + ' ( link_name '
                else:
                    if self.use_jun == False:
                        title='set ' + set_title_ + ' (i, j '
                    else:
                        title='set ' + set_title_ + ' (i, jun_set, j '
            else:
                title='set ' + set_title_ + ' (i'
        elif id == 'none' or id =='group':
            title='set '+set_title_ + ' ('

        for set in set_collections:
            if(title.endswith('(') ):
                if set == 'to_NODE_type' or set == 'from_NODE_type':
                    title = title + 'nodes_types'
                else:
                    title = title + set
            else:

                if set =='to_NODE_type' or set=='from_NODE_type':
                    title=title+',nodes_types'
                else:
                    title = title +','+set
        title=title+')\n/'
        attr_outputs.append('')
        attr_outputs.append(title)
        ##################
        for resource in resources:
            line=''
            if id == 'default':
                if islink:
                    if self.links_as_name:
                        line=resource.name
                    else:
                        if self.use_jun == False:
                            line=resource.from_node + ' . ' + resource.to_node
                        else:
                            jun = self.junc_node[resource.name]
                            line=resource.from_node + ' . ' + jun + ' . ' + resource.to_node
                else:
                    line=resource.name
            for set in set_collections:
                    if(islink ==True):
                        if set== 'to_NODE_type':
                            tt=self.network.get_node(node_name=resource.to_node).get_type_by_template(self.template_id)
                            if line:
                                line = line + ' . '+tt.name
                            else:
                                line=tt
                        elif  set == 'from_NODE_type':
                            tt=self.network.get_node(node_name=resource.from_node).get_type_by_template(self.template_id)
                            if line:
                                line = line + ' . '+tt.name
                            else:
                                line=tt
                        elif set == 'links_types':
                            tt=self.network.get_link(link_name=resource.name).get_type_by_template(self.template_id)
                            if line:
                                line = line + ' . ' + tt.name
                            else:
                                line = tt
                        else:
                            tt=resource.get_attribute(attr_name=set)
                            if tt==None:
                                break
                            if line:
                                line=line+' . '+tt.value
                            else:
                                line =  tt.value
            if(line):
                 attr_outputs.append(line)


        return '\n'.join(attr_outputs)

    ##########################


    def export_arrays(self, resources):
        """Export arrays.
        """
        attributes = []
        attr_names = []
        attr_outputs = []
        ff='{0:<'+self.name_len+'}'
        for resource in resources:
            for attr in resource.attributes:
                if attr.dataset_type == 'array' and attr.is_var is False:
                    attr.name = translate_attr_name(attr.name)
                    if attr.name not in attr_names:
                        attributes.append(attr)
                        attr_names.append(attr.name)
        if len(attributes) > 0:
            # We have to write the complete array information for every single
            # node, because they might have different sizes.
             att_res_dims={}
             for attribute in attributes:
                # This exporter only supports 'rectangular' arrays
                dim_=None
                for resource in resources:
                    attr = resource.get_attribute(attr_name=attribute.name)
                    if attr is not None and attr.value is not None:
                        array=json.loads(attr.value)
                        dim = self.get_dim(array)
                        if (dim_ is None):
                            dim_=dim
                        elif(dim > dim_):
                            dim_=dim
                att_res_dims[attribute]=dim
             for attribute in attributes:
                # This exporter only supports 'rectangular' arrays
                dim=att_res_dims[attribute]
                if len(dim) is not 1:
                    continue

                attr_outputs.append('* Array for attribute %s, ' % \
                            (attribute.name))
                attr_outputs.append('dimensions are %s\n\n' % dim)
                        # Generate array indices
                attr_outputs.append('SETS\n\n')
                indexvars = list(ascii_lowercase)
                attr_outputs.append(attribute.name +"_index"+'/\n')
                if(len(dim)==1):
                    for idx in range(dim[0]):
                        attr_outputs.append(str(idx+1) + '\n')
                attr_outputs.append('/\n')
                attr_outputs.append('Table '+  attribute.name + ' (i, *)\n\n')#+attribute.name+'_index)\n\n')
                attr_outputs.append(ff.format(''))
                for k  in range (dim[0]):
                    attr_outputs.append(ff.format(str(k+1)))
                attr_outputs.append('\n')

                for resource in resources:
                    attr = resource.get_attribute(attr_name=attribute.name)
                    if attr is not None and attr.value is not None:
                        array=json.loads(attr.value)
                        #dim = self.get_dim(array)
                        '''
                        for i, n in enumerate(dim):
                            attr_outputs.append(indexvars[i] + '_' + resource.name \
                                + '_' + attr.name+"_"+str(i))
                            if i < (len(dim) - 1):
                                attr_outputs.append(',')
                        attr_outputs.append(') \n\n')

                        ydim = dim[-1]

                        if len(dim)>1:
                            for y in range(ydim):
                                attr_outputs.append('{0:20}'.format(y))
                            attr_outputs.append('\n')
                        '''
                        i=0
                        attr_outputs.append(ff.format(resource.name))
                        if(len(dim) is 1):
                            for k  in range (dim[0]):
                                if len(array)==dim[0]:
                                    item=array[k]
                                elif len(array[0])==dim[0]:
                                     item=array[0][k]

                                ##attr_outputs.append("\n")
                                c=0
                                if(item is None):
                                    pass
                                elif type(item) is list:
                                    attr_outputs.append(format(str(i) + " . " + str(c)))
                                    i+=1
                                    for value in item:
                                        if c is 0:
                                           attr_outputs.append('{0:15}'.format(value))
                                        else:
                                             attr_outputs.append('{0:20}'.format(value))
                                        c+=1
                                else:
                                    #attr_outputs.append(format(str(i)))
                                    i+=1
                                    if c is 0:
                                        attr_outputs.append(ff.format(item))
                                    else:
                                        attr_outputs.append(ff.format(item))
                                    c+=1
                            attr_outputs.append('\n')
        attr_outputs.append('\n\n')
        return attr_outputs


    def get_years_months_days(self):
        '''
        used to get years, months days in time axis to
         write them in case of use_gams_date_index is true
        '''
        years=[]
        months=[]
        days=[]
        for date in self.time_axis:
            if date.year in years:
                pass
            else:
                years.append(date.year)
            if date.month in months:
                pass
            else:
                months.append(date.month)
            if date.day in days:
                pass
            else:
                days.append((date.day))
        return years, months, days

    def write_time_index(self):
        """
            Using the time-axis determined in __init__, write the time
            axis to the output file.
        """
        if(self.time_axis is None):
            return
        log.info("Writing time index")

        self.times_table={}
        try:
            if self.use_gams_date_index is True:
                years, months, days= self.get_years_months_days()

                t='SETS\n yr  /\n'
                for year in years:
                    t=t+str(year)+'\n'
                t=t+'/\n\n'

                t=t+'SETS\n mn  /\n'
                for month in months:
                    t=t+str(month)+'\n'
                t=t+'/\n\n'
                t=t+'SETS\n dy  /\n'
                for day in days:
                      t=t+str(day)+'\n'
                #t=t+'/\n\n'
                time_index = [t+'\n\n']####', '* Time index\n','t(yr, mn, dy)  time index /\n']
            else:
                time_index = ['SETS\n\n', '* Time index\n','t time index /\n']

            t = 0
            for date in self.time_axis:
                self.time_index.append(date)
                if self.use_gams_date_index is True:
                     _t=str(date.year)+" . "+str(date.month)+" . "+str(date.day)
                     self.times_table[date]=_t
                else:
                     time_index.append('%s\n' % t)
                     self.times_table[date]=t
                t += 1

            time_index.append('/\n\n')

            time_index.append('* define time steps dependent on time index (t)\n\n')
            if self.use_gams_date_index is True:
                time_index.append('Parameter timestamp(yr, mn, dy) ;\n\n')
            else:
                time_index.append('Parameter timestamp(t) ;\n\n')
            ##print "wrinting time"
            for t, date in enumerate(self.time_index):
                if self.use_gams_date_index is True:
                    keyy=str(date.year)+"\",\""+str(date.month)+"\", \""+str(date.day)
                    time_index.append('    timestamp("%s") = %s ;\n' % \
                    (keyy, convert_date_to_timeindex(date)))
                else:
                    time_index.append('    timestamp("%s") = %s ;\n' % \
                    (self.times_table[date], convert_date_to_timeindex(date)))
            time_index.append('\n\n')

            self.output = self.output + ''.join(time_index)
            log.info("Time index written")
        except Exception as e:
            log.exception(e)
            raise HydraPluginError("Please check time-axis or start time, end times and time step.")

    def write_descriptors(self):
        log.info("Writing descriptor sets %s.", self.filename)
        for key in self.descriptors:
            self.sets +=('\nset '+key+'\n/')
            for val in self.descriptors[key]:
                self.sets +=('\n' + str(val))
            self.sets += ('\n/\n\n')


    def write_direct_outputs(self):
        log.info("Writing direct outputs")
        for formatted_text in self.direct_outputs:
            self.sets += '\n'
            self.sets += formatted_text
            self.sets += '\n'

    def write_file(self):
        log.info("Writing file %s.", self.filename)

        for key in self.hashtables_keys:
            self.sets += ('\n' + key + '\n/')
            for val in self.hashtables_keys[key]:
                self.sets += ('\n' + str(val))
            self.sets += ('\n/\n\n')


        self.sets += '* empty groups\n\n'
        log.info(g.name for g in self.empty_groups)
        #keep a list of the group names which have been rendered in case
        #empty groups have been added twice
        rendered_groups = []

        for empty_group in self.empty_groups:

            if empty_group.name in rendered_groups:
                log.info("Duplicate empty group %s found. Ignoring", empty_group.name)
                continue

            try:
                index = empty_group.layout.get('index', "(*)")
            except:
                index = "(*)"
            if int(self.group_dimensions.get(empty_group.name, 1)) > 1:
                indices = ['*'] * int(self.group_dimensions[empty_group.name])
                index = "(" + ",".join(indices) + ")"

            #check if an index is specified i the group's layout
            try:
                group_layout = json.loads(empty_group.layout)
                index = group_layout.get('index', index)
            except:
                pass

            self.sets += ('\n' + empty_group.name + index + '\n/')
            self.sets += ('\n/\n\n')

            rendered_groups.append(empty_group.name)

        self.write_direct_outputs()

        with open(self.filename, 'w') as f:
            f.write(self.sets + self.output)

def translate_attr_name(name):
    """Replace non alphanumeric characters with '_'. This function throws an
    error, if the first letter of an attribute name is not an alphabetic
    character.
    """
    if isinstance(name, str):
        translator = ''.join(chr(c) if chr(c).isalnum()
                             else '_' for c in range(256))

    name = name.translate(translator)
    return name

def get_dict(obj):
    if type(obj) is list:
        list_results=[]
        for item in obj:
            list_results.append(get_dict(item))
        return list_results

    if not hasattr(obj, "__dict__"):
         return obj

    result = {}
    for key, val in obj.__dict__.items():
        if key.startswith("_"):
            continue
        if isinstance(val, list):
            element = []
            for item in val:
                element.append(get_dict(item))
        else:
            element = get_dict(obj.__dict__[key])
        result[key] = element
    return result

def get_resourcescenarios_ids(resourcescenarios):
    resourcescenarios_ids={}
    for res in resourcescenarios:
        ##print "==============================>", get_dict(res)
        ##print type(res)
        resourcescenarios_ids[res.resource_attr_id]=res
    return resourcescenarios_ids
