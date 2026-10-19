"""Logic of the ALARM ArcGIS tools that does not need arcpy.

Keeping it separate from ALARM_Tools.pyt makes it testable with plain pytest and keeps the
toolbox file short: the .pyt only wires parameters and messages to these functions.
"""
