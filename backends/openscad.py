#bolttools - a framework for creation of part libraries
#Copyright (C) 2013 Johannes Reinhardt <jreinhardt@ist-dein-freund.de>
#
#This library is free software; you can redistribute it and/or
#modify it under the terms of the GNU Lesser General Public
#License as published by the Free Software Foundation; either
#version 2.1 of the License, or any later version.
#
#This library is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#Lesser General Public License for more details.
#
#You should have received a copy of the GNU Lesser General Public
#License along with this library; if not, write to the Free Software
#Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

from os import listdir,makedirs
from os.path import join, basename
from shutil import copy
# pylint: disable=W0622
from codecs import open
import license
from datetime import datetime
import re

from errors import *
from common import BackendExporter

def get_signature(cl,params):
	arg_strings = []
	for pname in params.free:
		if params.types[pname] in ["String","Table Index"]:
			arg_strings.append('%s="%s"' % (pname,params.defaults[pname]))
		elif params.types[pname] == "Bool":
			arg_strings.append('%s=%s' % (pname,str(params.defaults[pname]).lower()))
		else:
			arg_strings.append('%s=%s' % (pname,params.defaults[pname]))
	arg_strings.append('part_mode="default"')
	return ', '.join(arg_strings)

def get_incantation(cl,params):
	return '%s(%s)' % (cl.openscadname, get_signature(cl,params))

def format_string(template,substitute,args):
	t = template.replace("%d","%s").replace("%f","%s").replace("%g","%s")
	subst = t % tuple('",%s,"' % args[s] for s in substitute)
	return 'str("' + subst + '")'

class OpenSCADExporter(BackendExporter):
	def __init__(self,repo,databases):
		BackendExporter.__init__(self,repo,databases)
		self.openscad = databases["openscad"]

		#check for module name clashes
		modules = []
		for coll in repo.collections:
			for cl in coll.classes:
				if cl.openscadname in modules:
					raise ModuleNameCollisionError(cl.openscadname)
				modules.append(cl.openscadname);
		for base in self.openscad.getbase.values():
			if base.type == "module":
				if base.name in modules:
					raise ModuleNameCollisionError(base.name)

	def write_output(self,out_path,target_license,version,stable=False):
		oscad = self.openscad

		self.clear_output_dir(out_path)
		#copy files
		bolts_fid = open(join(out_path,"BOLTS.scad"),"w","utf8")
		standard_fids = {}
		for std in self.repo.standard_bodies:
			standard_fids[std] = open(join(out_path,"BOLTS_%s.scad" % std),"w","utf8")

		makedirs(join(out_path,"tables"))

		#copy common files
		if not license.is_combinable_with("LGPL 2.1+",target_license):
			raise IncompatibleLicenseError("OpenSCAD common files are licensed under LGPL 2.1+, which is not compatible with %s" % target_license)
		makedirs(join(out_path,"common"))
		for filename in listdir(join(self.repo.path,"backends","openscad")):
			if not filename.endswith(".scad"):
				continue
			copy(join(self.repo.path,"backends","openscad",filename),
				join(out_path,"common",filename))
			bolts_fid.write("include <common/%s>\n" % filename)
			for std in standard_fids:
				standard_fids[std].write("include <common/%s>\n" % filename)

		#create version file
		version_fid = open(join(out_path,"common","version.scad"),"w","utf8")
		if stable:
			major, minor = str(version).split('.')
			version_fid.write('function BOLTS_version() = [%s, %s, %s];\n' %
				 (major, minor, target_license))
		else:
			version_fid.write('function BOLTS_version() = "%s";\n' % version)
		date = datetime.now()
		version_fid.write('function BOLTS_date() = [%d,%d,%d];\n' %
				(date.year, date.month, date.day))
		version_fid.write('function BOLTS_license() = "%s";\n' % target_license)
		version_fid.close()
		bolts_fid.write("include <common/version.scad>\n")
		for std in standard_fids:
			standard_fids[std].write("include <common/version.scad>\n")

		#copy base files
		copied = []
		makedirs(join(out_path,"base"))
		for id in oscad.getbase:
			base = oscad.getbase[id]
			if not license.is_combinable_with(base.license_name,target_license):
				continue
			for path in base.get_copy_files():
				if path in copied:
					continue
				copy(join(oscad.backend_root,path),join(out_path,"base",basename(path)))
				copied.append(path)

		#include files
		included = []
		for id in oscad.getbase:
			base = oscad.getbase[id]
			if not license.is_combinable_with(base.license_name,target_license):
				continue
			for path in base.get_include_files():
				if path in included:
					continue
				bolts_fid.write("include <base/%s>\n" % path)
				for std in standard_fids:
					standard_fids[std].write("include <base/%s>\n" % path)
				included.append(path)

		#write tables
		for collection in self.repo.collections:
			if not license.is_combinable_with(collection.license_name,target_license):
				continue
			for cl in collection.classes_by_ids():
				if not cl.id in oscad.getbase:
					continue
				base = oscad.getbase[cl.id]
				if not license.is_combinable_with(base.license_name,target_license):
					continue
				table_path = join("tables","%s_table.scad" % cl.id)
				table_filename = join(out_path,table_path)
				fid = open(table_filename,"w","utf8")
				self.write_table(fid,collection,cl)
				fid.close()

				bolts_fid.write("include <%s>\n" % table_path)
				for std in standard_fids:
					if cl in self.repo.standardized[std]:
						standard_fids[std].write("include <%s>\n" % table_path)
		bolts_fid.write("\n\n")

		#write stubs
		for collection in self.repo.collections:
			if not license.is_combinable_with(collection.license_name,target_license):
				continue
			for cl in collection.classes:
				if not cl.id in oscad.getbase:
					continue
				base = oscad.getbase[cl.id]
				if not license.is_combinable_with(base.license_name,target_license):
					continue
				self.write_stub(bolts_fid,cl)
				self.write_dim_accessor(bolts_fid,cl)
				self.write_connectors_accessor(bolts_fid,cl)
				for std in standard_fids:
					if cl in self.repo.standardized[std]:
						self.write_stub(standard_fids[std],cl)
						self.write_dim_accessor(standard_fids[std],cl)
		bolts_fid.close()
		for std in standard_fids:
			standard_fids[std].close()

	def write_table(self,fid,collection,cl):
		fid.write("/* Generated by BOLTS, do not modify */\n")
		fid.write("/* Copyright by: %s */\n" % ",".join(collection.authors))
		fid.write("/* %s */\n" % collection.license)

		for table,i in zip(cl.parameters.tables,range(len(cl.parameters.tables))):
			fid.write("function %s_table_%d(idx) = \n" % (cl.id,i))
			fid.write("//%s\n" % ", ".join(table.columns))
			for k,values in table.data.iteritems():
				data = ["None" if v is None else v for v in values]
				fid.write('idx == "%s" ? %s : \n' % (k,str(data).replace("'",'"')))
			fid.write('"Error";\n\n')

		for table,i in zip(cl.parameters.tables2d,range(len(cl.parameters.tables2d))):
			fid.write("function %s_table2d_%d(rowidx,colidx) = \n" % (cl.id,i))
			for col,j in zip(table.columns,range(len(table.columns))):
				fid.write('colidx == "%s" ? %s_table2d_rows_%d(rowidx)[%d] : \n' % (col,cl.id,i,j))
			fid.write('"Error";\n\n')

			fid.write("function %s_table2d_rows_%d(rowidx) = \n" % (cl.id,i))
			for k,values in table.data.iteritems():
				data = ["None" if v is None else v for v in values]
				fid.write('rowidx == "%s" ? %s : \n' % (k,str(data).replace("'",'"')))
			fid.write('"Error";\n\n')


	def write_dim_accessor(self,fid,cl):
		units = {"Length (mm)" : "mm", "Length (in)" : "in"}
		#collect textual parameter representations
		args = {}
		if not cl.standard is None:
			args['standard'] = '"%s"' % cl.name
		#class parameters
		params = cl.parameters.union(self.openscad.getbase[cl.id].parameters)
		for pname in params.free:
			args[pname] = pname
		args.update(params.literal)
		for table,i in zip(params.tables,range(len(params.tables))):
			for pname,j in zip(table.columns,range(len(table.columns))):
				if params.types[pname] in units:
					unit = units[params.types[pname]]
					args[pname] = 'convert_to_default_unit(%s_table_%d(%s)[%d],"%s")' % (cl.id,i,table.index,j,unit)
				else:
					args[pname] = '%s_table_%d(%s)[%d]' % (cl.id,i,table.index,j)
		for table,i in zip(params.tables2d,range(len(params.tables2d))):
			pname = table.result
			if params.types[pname] in units:
				unit = units[params.types[pname]]
				args[pname] = 'convert_to_default_unit(%s_table2d_%d(%s,%s),"%s")' % (cl.id,i,table.rowindex,table.colindex,unit)
			else:
				args[pname] = '%s_table2d_%d(%s,%s)' % (cl.id,i,table.rowindex,table.colindex)
		fid.write("function %s_dims(%s) = [\n\t" % (cl.openscadname, get_signature(cl,params)))
		fid.write(",\n\t".join('["%s", %s]' % (pname,args[pname]) for pname in params.parameters))
		fid.write("];\n\n")

	def write_connectors_accessor(self,fid,cl):
		units = {"Length (mm)" : "mm", "Length (in)" : "in"}
		#collect textual parameter representations
		args = {}
		if not cl.standard is None:
			args['standard'] = '"%s"' % cl.name
		base = self.openscad.getbase[cl.id]

		#do nothing if no connectors are specified
		if base.connectors is None:
			return
		#class parameters
		params = cl.parameters.union(base.parameters)
		for pname in params.free:
			args[pname] = pname
		args.update(params.literal)
		args["location"] = "location";
		for table,i in zip(params.tables,range(len(params.tables))):
			for pname,j in zip(table.columns,range(len(table.columns))):
				if params.types[pname] in units:
					unit = units[params.types[pname]]
					args[pname] = 'convert_to_default_unit(%s_table_%d(%s)[%d],"%s")' % (cl.id,i,table.index,j,unit)
				else:
					args[pname] = '%s_table_%d(%s)[%d]' % (cl.id,i,table.index,j)
		for table,i in zip(params.tables2d,range(len(params.tables2d))):
			pname = table.result
			if params.types[pname] in units:
				unit = units[params.types[pname]]
				args[pname] = 'convert_to_default_unit(%s_table2d_%d(%s,%s),"%s")' % (cl.id,i,table.rowindex,table.colindex,unit)
			else:
				args[pname] = '%s_table2d_%d(%s,%s)' % (cl.id,i,table.rowindex,table.colindex)
		call = "%s(%s)" % (base.connectors.name, ", ".join(args[arg] for arg in base.connectors.arguments))

		fid.write("function %s_conn(location,%s) = new_cs(\n" % (cl.openscadname, get_signature(cl,params)))
		fid.write("\torigin=%s[0],\n\taxes=%s[1]);\n\n" % (call,call))

	def write_stub(self,fid,cl):
		units = {"Length (mm)" : "mm", "Length (in)" : "in"}
		#collect textual parameter representations
		args = {}
		if not cl.standard is None:
			args['standard'] = '"%s"' % cl.name
		#class parameters
		params = cl.parameters.union(self.openscad.getbase[cl.id].parameters)
		for pname in params.free:
			args[pname] = pname
		args.update(params.literal)
		for table,i in zip(params.tables,range(len(params.tables))):
			for pname,j in zip(table.columns,range(len(table.columns))):
				if params.types[pname] in units:
					unit = units[params.types[pname]]
					args[pname] = 'convert_to_default_unit(measures_%d[%d],"%s")' % (i,j,unit)
				else:
					args[pname] = 'measures_%d[%d]' % (i,j)
		for table,i in zip(params.tables2d,range(len(params.tables2d))):
			pname = table.result
			if params.types[pname] in units:
				unit = units[params.types[pname]]
				args[pname] = 'convert_to_default_unit(measures2d_%d,"%s")' % (i,unit)
			else:
				args[pname] = 'measures2d_%d' % (i)

		#incantation
		fid.write("module %s{\n" % get_incantation(cl,params))

		#warnings and type checks
		if cl.status == "withdrawn":
			fid.write("""\tBOLTS_warning("The standard %s is withdrawn.
Although withdrawn standards are often still in use,
it might be better to use its successor %s instead");\n""" %
				(cl.name,cl.replacedby))
		for pname in params.free:
			fid.write('\tcheck_parameter_type("%s","%s",%s,"%s");\n' %
				(cl.name,pname,args[pname],params.types[pname]))

		fid.write("\n")
	

		#load table data
		for table,i in zip(cl.parameters.tables,range(len(cl.parameters.tables))):
			fid.write('\tmeasures_%d = %s_table_%d(%s);\n' %
				(i,cl.id,i,table.index))
			fid.write('\tif(measures_%d == "Error"){\n' % i)
			fid.write('\t\tBOLTS_error("Table look-up failed in %s, table %d");\n\t}\n' %
				(cl.name,i))

		for table,i in zip(cl.parameters.tables2d,range(len(cl.parameters.tables2d))):
			fid.write('\tmeasures2d_%d = %s_table2d_%d(%s,%s);\n' %
				(i,cl.id,i,table.rowindex, table.colindex))
			fid.write('\tif(measures2d_%d == "Error"){\n' % i)
			fid.write('\t\tBOLTS_error("Table look-up failed in %s, table2d %d");\n\t}\n' %
				(cl.name,i))

		fid.write('\tif(BOLTS_MODE == "bom"){\n')
		fid.write('\t\tif(!(part_mode == "diff")){\n')

		#write part name output for bom
		argc = 0
		fid.write('\t\t\techo(')
		fid.write(format_string(cl.naming.template,cl.naming.substitute,args))
		fid.write(");\n")
		#To avoid problems with missing top level object
		fid.write("\t\t}\n")
		fid.write("\t\tcube();\n")
		fid.write("\t} else {\n")

		#module call
		fid.write('\t\t%s;\n\t}\n}\n\n' %
			self.openscad.getbase[cl.id].get_incantation(args))

