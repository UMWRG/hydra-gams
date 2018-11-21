#!/usr/bin env python
"""Assign a type to all nodes and links.
"""

from HydraLib import PluginLib

from lxml import etree

cli = PluginLib.connect()

with open('template.xml') as f:
    xml_template = f.read()

template = cli.service.upload_template_xml(xml_template)

node_type_dict = {('Ag1', 'Ag2', 'EndPt'): 'ag',
                  ('Desal1'): 'desal',
                  ('GW1', 'GW2'): 'gw',
                  ('Hp1'): 'hp',
                  ('J1', 'J2', 'J3'): 'jn',
                  ('SR1', 'SR2', 'SR3', 'SR4'): 'sr',
                  ('Urb1', 'Urb2'): 'ur',
                  ('WWTP1'): 'WWTP'}

link_type_dict = {('GW1_Urb1', 'Desal1_Urb2', 'WWTP1_Urb2', 'WWTP1_J2',
                   'GW2_Ag2', 'GW2_Ag1'): 'costLink',
                  ('SR1_J1', 'J1_SR2', 'SR1_Urb1', 'Urb1_J1', 'Urb1_GW1',
                   'SR2_SR4', 'SR4_J2', 'Ag1_GW2', 'Ag2_GW2', 'Urb2_WWTP1',
                   'SR4_Urb2', 'SR3_Hp1', 'Hp1_SR4', 'J2_J3', 'Ag2_J3',
                   'Ag1_J2', 'SR4_Ag1', 'J2_Ag2', 'J3_EndPt'): 'defLink'}
network_type_name = 'hydro-econ'

type_ids = dict()

for type_name in node_type_dict.values():
    for tmpltype in template.types.TemplateType:
        if tmpltype.name == type_name:
            type_ids.update({tmpltype.name: tmpltype.id})
            break

for type_name in link_type_dict.values():
    for tmpltype in template.types.TemplateType:
        if tmpltype.name == type_name:
            type_ids.update({tmpltype.name: tmpltype.id})
            break

for tmpltype in template.types.TemplateType:
    if tmpltype.name == network_type_name:
        type_ids.update({tmpltype.name: tmpltype.id})
        break

with open('result.xml') as f:
    result_xml = f.read()

plugin_output = etree.XML(result_xml)

for element in plugin_output:
    if element.tag == 'network_id':
        network_id = int(element.text)
        break

network = cli.service.get_network(network_id, 'N')

for node in network.nodes.Node:
    for node_name_list in node_type_dict.keys():
        if node.name in node_name_list:
            type_id = type_ids[node_type_dict[node_name_list]]
            cli.service.assign_type_to_resource(type_id, 'NODE', node.id)


for link in network.links.Link:
    for link_name_list in link_type_dict.keys():
        if link.name in link_name_list:
            type_id = type_ids[link_type_dict[link_name_list]]
            cli.service.assign_type_to_resource(type_id, 'LINK', link.id)

cli.service.assign_type_to_resource(type_ids[network_type_name], \
                                    'NETWORK', network_id)
