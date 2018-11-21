# (c) Copyright 2013, 2014, 2015 University of Manchester\

"""A Hydra plug-in to export a network and a scenario to a set of files, which
can be imported into a GAMS model.

The GAMS import plug-in provides an easy to use tool for exporting data from
HydraPlatform to custom GAMS models. The basic idea is that this plug-in
exports a network and associated data from HydraPlatform to a text file which
can be imported into an existing GAMS model using the ``$ import`` statement.

Using the commandline tool
--------------------------

**Mandatory arguments:**

====================== ======= ========== ======================================
Option                 Short   Parameter  Description
====================== ======= ========== ======================================
--network              -t      NETWORK    ID of the network that will be
                                          exported.
--scenario             -s      SCENARIO   ID of the scenario that will be
                                          exported.
--template-id          -tp     TEMPLATE   ID of the template used for exporting
                                          resources. Attributes that don't
                                          belong to this template are ignored.
--output               -o      OUTPUT     Filename of the output file.
====================== ======= ========== ======================================

**Optional arguments:**

====================== ======= ========== ======================================
Option                 Short   Parameter  Description
====================== ======= ========== ======================================
--group-nodes-by       -gn     GROUP_ATTR Group nodes by this attribute(s).
--group_links-by       -gl     GROUP_ATTR Group links by this attribute(s).
====================== ======= ========== ======================================

**Switches:**

====================== ====== =========================================
Option                 Short  Description
====================== ====== =========================================
--export_by_type       -et    Set export data based on types or based
                              on attributes only, default is export
                              data by attributes unless this option
                              is set.
====================== ====== =========================================


Specifying the time axis
~~~~~~~~~~~~~~~~~~~~~~~~

One of the following two options for specifying the time domain of the model is
mandatory:

**Option 1:**

====================== ======= ========== ======================================
--start-date           -st     START_DATE Start date of the time period used for
                                          simulation.
--end-date             -en     END_DATE   End date of the time period used for
                                          simulation.
--time-step            -dt     TIME_STEP  Time step used for simulation. The
                                          time step needs to be specified as a
                                          valid time length as supported by
                                          Hydra's unit conversion function (e.g.
                                          1 s, 3 min, 2 h, 4 day, 1 mon, 1 yr)
====================== ======= ========== ======================================

**Option 2:**

====================== ======= ========== ======================================
--time-axis            -tx     TIME_AXIS  Time axis for the modelling period (a
                                          list of comma separated time stamps).
====================== ======= ========== ======================================


Input data for GAMS
-------------------

.. note::

    The main goal of this plug-in is to provide a *generic* tool for exporting
    network topologies and data to a file readable by GAMS. In most cases it
    will be necessary to adapt existing GAMS models to the naming conventions
    used by this plug-in.

Network topology
~~~~~~~~~~~~~~~~

Nodes are exported to GAMS by name and referenced by index ``i``::

    SETS

    i vector of all nodes /
    NodeA
    NodeB
    NodeC
    /

The representation of links based on node names. The set of links therefore
refers to the list of nodes. Because there are always two nodes that are
connected by a link, the list of link refers to the index of nodes::

    Alias(i,j)

    SETS

    links(i,j) vector of all links /
    NodeA . NodeB
    NodeB . NodeC
    /

In addition to links, GAMSExport provides a connectivity matrx::

    * Connectivity matrix.
    Table Connect(i,j)
                    NodeA     NodeB     NodeC
    NodeA               0         1         0
    NodeB               0         0         1
    NodeC               0         0         0


Nodes and links are also grouped by node type::

    * Node groups

    Ntype1(i) /
    NodeA
    NodeB
    /

    Ntype2(i) /
    NodeC
    /

    * Link groups

    Ltype1(i,j) /
    NodeA . NodeB
    NodeB . NodeC
    /

If you want to learn more about node and link types, please refer to the Hydra
documentation.


Datasets
~~~~~~~~

There are four types of parameters that can be exported: scalars, descriptors,
time series and arrays. Because of the way datasets are translated to GAMS
code, data used for the same attribute of different nodes and links need to be
of the same type (scalar, descriptor, time series, array). This restriction
applies for nodes and links that are of the same type. For example, ``NodeA``
and ``NodeB`` have node type ``Ntype1``, both have an attribute ``atttr_a``.
Then both values for ``attr_a`` need to be a scalar (or both need to be a
descriptor, ...). It is also possible that one node does not have a value for
one specific attribute, while other nodes of the same type do. In this case,
make sure that the GAMS mode code supports this.

Scalars and Descriptors:
    Scalars and descriptors are exported based on node and link types. All
    scalar datasets of each node (within one node type) are exported into one
    table::

        SETS

        Ntype1_scalars /
        attr_a
        attr_c
        /

        Table Ntype1_scalar_data(i, Ntype1_scalars)

                        attr_a      attr_c
        NodeA              1.0         2.0
        NodeB           3.1415         0.0

    Descriptors are handled in exactly the same way.

Time series:
    For all time series exported, a common time index is defined::

        SETS

        * Time index
        t time index /
        0
        1
        2
        /

    In case the length of each time step is not uniform and it is used in the
    model, timestamps corresponding to each time index are stored in the
    ``timestamp`` parameter::

        Parameter timestamp(t) ;

            timestamp("0") = 730851.0 ;
            timestamp("1") = 730882.0 ;
            timestamp("2") = 730910.0 ;

    Timestamps correspond to the Gregorian ordinal of the date, where the value
    of 1 corresponds to January 1, year 1.

    Similar to scalars and descriptors, time series for one node or link type
    are summarised in one table::

        SETS

        Ntype1_timeseries /
        attr_b
        attr_d
        /

        Table Ntype1_timeseries_data(t,i,Ntype1_timeseries)

                NodeA.attr_b    NodeB.attr_b    NodeA.attr_d    NodeB.attr_b
        0                1.0            21.1          1001.2          1011.4
        1                2.0            21.0          1003.1          1109.0
        2                3.0            20.9          1005.7          1213.2



Arrays:
    Due to their nature, arrays can not be summarised by node type. For every
    array that is exported a complete structure needs to be defined. It is best
    to show this structure based on an example::

        * Array attr_e for node NodeC, dimensions are [2, 2]

        SETS

        a_NodeC_attr_e array index /
        0
        1
        /

        b_NodeC_attr_e array index /
        0
        1
        /

        Table NodeC_attr_e(a_NodeC_attr_e,b_NodeC_attr_e)

                    0       1
        0         5.0     6.0
        1         7.0     8.0

    For every additional dimension a new index is created based on letters (a
    to z). This also restricts the maximum dimensions of an array to 26.  We
    are willing to increase this restriction to 676 or more as soon as somebody
    presents us with a real-world problem that needs arrays with more than 26
    dimensions.

Examples:
=========
Exporting use time axis:
 hydra-gams export -t 4 -s 4  -tx 2000-01-01, 2000-02-01, 2000-03-01, 2000-04-01, 2000-05-01, 2000-06-01 -o "c:\temp\demo_2.dat"

Exporting use start time, end time and time step:

 hydra-gams export -t 40 -s 40  -st 2015-04-01 -en  2039-04-01 -dt "1 yr"  -o "c:\temp\CH2M_2.dat" -et
 hydra-gams export -s 37 -t 37 -o "F:\work\CAL_Model\csv data for California model\excel files final\input_f.txt" -st "1922-01-01"  -en "1993-12-01" -dt "1 mon"
"""

from .exporter import GAMSExporter, export_network


