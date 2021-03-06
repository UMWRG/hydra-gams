$TITLE    hydro-econ.gms
** J. Harou, ...
* Start date: 2009-8-5
* copyright: University College London, ...
* license: GPL v>2.0
* Description:
* Hydro-economic model GAMS template to illustrate GAMS-HydroPlatform connection
* This code is designed to work with any network exported by HydroPlatform
* (using the same 'Object Types' as in our HydroPlatform example).

Option domlim=100;
Option Limcol=0;
Option Limrow=1500;

** ----------------------------------------------------------------------
**  Loading Data: sets, parameters and tables
** ----------------------------------------------------------------------

* Load set definitions and all parameters, tables and time-series data (choose A or B)

* Option A: load data using text files generated by HydroPlatform
*$        include hydraoutput.txt
*$        include data_full.txt
*$        include network.txt
*$        include data.txt
* Option B: load data using a single Excel file (using GAMS GDX utilities)
*$        include GAMS_gdx_import.txt
* (NB.: GAMS_gdx_import.txt must be written by modeler, data.xls is generated by HydroPlatform)

* Import data from an excel file
*$CALL GDXXRW.EXE hp_gams_export.xls

*Parameter sr(i);
*Parameter gw(i);
*Parameter desal(i);

*$GDXIN hp_gams_export.gdx
*$LOAD sr
*$LOAD gw
*$LOAD desal
*$GDXIN


* Define further subsets to simplify model formulation equations
*        (in this case the subsets are aggregations of subsets of i (nodes) )
$        include Subsets.txt

* Define parameters aggregating from different subsets to simplify model equations
$        include Aggregate_Parameters.txt


** ----------------------------------------------------------------------
**  Model variables and equations
** ----------------------------------------------------------------------

VARIABLES
     urBenefits(t,ur) urban benefits in network per demand node per time step
     urTotalBenefits(t)  urban benefits in network per demand node per time step
     agBenefits(t,ag)  agricultural benefits in network per time step
     agTotalBenefits(t)  agricultural benefits in network per time step
     totalCost(t)  costs in network per time step
     linkCost(t,i,j) costs incurred in each link in each time step
     totalNetBenefits total net benefits over time horizon (objective function to be maxed)
     Q(t,i,j) flow from node i to j during period yr-mn-dy
     S(t,i) storage in node stor
     delivery(t,i) total water delivery into each demand node
     infeasQ(t,i) artificial flow to prevent and diagnose infeasibilities
     infeasCost(t) cost of infeasibilities
     ;

POSITIVE VARIABLES
     Q, S,
     infeasQ
     ;

EQUATIONS
     EqMassBalNonStor(t,i)
     EqMassBalStor(t,i)
     EqMaxFlow(t,i,j)
     EqMinFlow(t,i,j)
     EqMaxStor(t,i)
     EqMinStor(t,i)
     EqSustStor(t,i)
     EqDemandInflows(t,i)
     EqUrbBenefits(t)
     EqAgBenefits(t)
     EqCosts(t)
     EqInfeasCosts(t)
     EqTotalNetBenefits
     EqUrbBenefitsPerDem(t,i)
     EqAgBenefitsPerDem(t,i)
     EqCostsPerLinkPerTS(t,i,j)
     ;

* Conservation of Mass at non-storage nodes:
EqMassBalNonStor(t,nonstor)..
         netInflows(t,nonstor)
         + infeasQ(t,nonstor)
         + SUM(j$Connect(j,nonstor), Q(t,j,nonstor))
         - SUM(j$Connect(nonstor,j), Q(t,nonstor,j) * lossCoeff(nonstor,j))
         - consum(nonstor)$dem(nonstor) * delivery(t,nonstor)
         =E= 0;

* Conservation of Mass at storage nodes:
EqMassBalStor(t,stor)..
         netInflows(t,stor)
         + infeasQ(t,stor)
         + SUM(j$Connect(j,stor), Q(t,j,stor))
         - SUM(j$Connect(stor,j), Q(t,stor,j) * lossCoeff(stor,j) )
         =E= S(t,stor)
             - initStor(t,stor)$(ord(t) EQ 1)
             - S(t--1,stor)$(ord(t) GT 1)
         ;

* Maximum and minimum flow constraints on links:
EqMaxFlow(t,i,j)$Connect(i,j)..   Q(t,i,j) =L= maxFlows(i,j);
EqMinFlow(t,i,j)$Connect(i,j)..   Q(t,i,j) =G= minFlows(i,j);

* Maximum and minimum storage at storage nodes:
EqMaxStor(t,stor).. S(t,stor) =L= maxStor(stor);
EqMinStor(t,stor).. S(t,stor) =G= minStor(stor);

* Sustainable storage end condition (final storage >= _% of initial storage):
EqSustStor(t,managedstor)$(ord(t) = card(t))..
          S(t,managedstor) =G= 1 * initStor(t,managedstor)  ;

* Summing inflows (deliveries) into demand nodes
EqDemandInflows(t,dem)..
         delivery(t,dem) =E= SUM(j$Connect(j,dem), Q(t,j,dem))
         + netInflows(t,dem) ;

* Inidividual urban demand benefits from water deliveries
EqUrbBenefits(t)..
         sum(ur,ur_scalar_data(ur,'linCoeff') * delivery(t,ur)
         + 0.5 * ur_scalar_data(ur,'quadCoeff') * delivery(t,ur)**2 )
         =E= urTotalBenefits(t) ;

* Agricultural benefits from water deliveries
EqAgBenefits(t)..
         SUM(ag, ag_timeseries_data(t,ag,'linCoeff') * delivery(t,ag)
         + 0.5 * ag_timeseries_data(t,ag,'quadCoeff') * delivery(t,ag)**2 )
         =E= agTotalBenefits(t) ;

* Costs
EqCosts(t)..
         SUM((i,j)$Connect(i,j), Q(t,i,j) * costLink_scalar_data(i,j,"cost"))
         =E= totalCost(t) ;

* Infeasability costs
EqInfeasCosts(t)..   SUM(i, infeasQ(t,i)*1000000) =E= infeasCost(t) ;


* Sum total net benefits over all time horizons
EqTotalNetBenefits..
         Sum((t),
         urTotalBenefits(t)
         + agTotalBenefits(t)
         - totalCost(t)
         - infeasCost(t)
         )
         =E= totalNetBenefits ;


*** The following equations are for reporting results only ***

* Inidividual urban demand benefits from water deliveries
EqUrbBenefitsPerDem(t,ur)..
         ur_scalar_data(ur,'linCoeff') * delivery(t,ur)
         + 0.5 * ur_scalar_data(ur,'quadCoeff') * delivery(t,ur)**2
         =E= urBenefits(t,ur) ;

* Inidividual Agricultural demand benefits from water deliveries
EqAgBenefitsPerDem(t,ag)..
         ag_timeseries_data(t,ag,'linCoeff') * delivery(t,ag)
         + 0.5 * ag_timeseries_data(t,ag,'quadCoeff') * delivery(t,ag)**2
         =E= agBenefits(t,ag) ;

* Costs generated by each link
EqCostsPerLinkPerTS(t,i,j)..
         Q(t,i,j) * costLink_scalar_data(i,j,"cost")
         =E= linkCost(t,i,j) ;

** ----------------------------------------------------------------------
**  Model declaration and solve statements
** ----------------------------------------------------------------------

Model genwaterv1 /all/ ;

Solve genwaterv1  MAXIMIZING totalNetBenefits USING NLP ;

option solprint = off ;

Display totalNetBenefits.l;


* Unload results to GDX file
execute_unload "genWaterResults.gdx" S,
    Q,
    delivery,
    infeasQ,
    infeasCost,
    urBenefits,
    urTotalBenefits,
    agBenefits,
    agTotalBenefits,
    linkCost,
    totalCost,
    totalNetBenefits

** ----------------------------------------------------------------------
**  Exporting results from GAMS to an EXCEL spreadsheet using GDX utility
** ----------------------------------------------------------------------

* Write to Excel file from GDX
*execute 'gdxxrw.exe genWaterResults.gdx var=infeasQ.l rng=InfeasQs! '
*execute 'gdxxrw.exe genWaterResults.gdx var=S.l rng=Storages! '
*execute 'gdxxrw.exe genWaterResults.gdx var=Q.l rng=Qs! Rdim=3 SQ=N '
*execute 'gdxxrw.exe genWaterResults.gdx var=delivery.l rng=deliveries! '
*execute 'gdxxrw.exe genWaterResults.gdx var=urBenefits.l rng=urbBenefits! '
*execute 'gdxxrw.exe genWaterResults.gdx var=agBenefits.l rng=agBenefits! '
*execute 'gdxxrw.exe genWaterResults.gdx var=linkCost.l rng=linkCosts! Rdim=3 SQ=N '
*execute 'gdxxrw.exe genWaterResults.gdx par=Connect rng=Connectivity! '
