#-------------------------------------------------------------------------------
# elftools: dwarf/callframe.py
#
# DWARF call frame information
#
# Eli Bendersky (eliben@gmail.com)
# This code is in the public domain
#-------------------------------------------------------------------------------
from ..common.utils import (struct_parse, dwarf_assert)
from .structs import DWARFStructs
from .constants import * 


class CallFrameInstruction(object):
    def __init__(self, opcode, args):
        self.opcode = opcode
        self.args = args

    def __repr__(self):
        return '%s (0x%x): %s' % (
            instruction_name(self.opcode), self.opcode, self.args)


class CIE(object):
    def __init__(self, header, instructions):
        self.header = header
        self.instructions = instructions

    def __getitem__(self, name):
        """ Implement dict-like access to header entries
        """
        return self.header[name]


class FDE(object):
    def __init__(self, header, instructions):
        self.header = header
        self.instructions = instructions

    def __getitem__(self, name):
        """ Implement dict-like access to header entries
        """
        return self.header[name]


class CallFrameInfo(object):
    def __init__(self, stream, size, base_structs):
        self.stream = stream
        self.size = size
        self.base_structs = base_structs
        self.entries = None

    def get_entries(self):
        if self.entries is None:
            self.entries = self._parse_entries()
        return self.entries

    def _parse_entries(self):
        entries = []
        offset = 0
        while offset < self.size:
            # Throughout the body of this loop, offset keeps pointing to the
            # beginning of the entry
            entry_length = struct_parse(
                self.base_structs.Dwarf_uint32(''), self.stream, offset)
            dwarf_format = 64 if entry_length == 0xFFFFFFFF else 32

            entry_structs = DWARFStructs(
                little_endian=self.base_structs.little_endian,
                dwarf_format=dwarf_format,
                address_size=self.base_structs.address_size)

            # Read the next field to see whether this is a CIE or FDE
            CIE_id = struct_parse(
                entry_structs.Dwarf_offset(''), self.stream)

            is_CIE = (
                (dwarf_format == 32 and CIE_id == 0xFFFFFFFF) or 
                CIE_id == 0xFFFFFFFFFFFFFFFF)

            if is_CIE:
                header_struct = entry_structs.Dwarf_CIE_header
            else:
                header_struct = entry_structs.Dwarf_FDE_header

            # Parse the header, which goes up to and including the
            # return_address_register field
            header = struct_parse(
                header_struct, self.stream, offset)

            # For convenience, compute the end offset for this entry
            end_offset = (
                offset + header.length +
                entry_structs.initial_length_field_size())

            # At this point self.stream is at the start of the instruction list
            # for this entry
            instructions = self._parse_instructions(
                entry_structs, self.stream.tell(), end_offset)

            new_entry_class = CIE if is_CIE else FDE
            entries.append(new_entry_class(
                header=header,
                instructions=instructions))
            # ZZZ: for FDE's, I need some offset->CIE mapping cache stored
            offset = self.stream.tell()
        return entries

    def _parse_instructions(self, structs, offset, end_offset):
        """ Parse a list of CFI instructions from self.stream, starting with
            the offset and until (not including) end_offset.
            Return a list of CallFrameInstruction objects.
        """
        instructions = []
        while offset < end_offset:
            opcode = struct_parse(structs.Dwarf_uint8(''), self.stream, offset)
            args = []

            primary = opcode & _PRIMARY_MASK
            primary_arg = opcode & _PRIMARY_ARG_MASK
            if primary == DW_CFA_advance_loc:
                args = [primary_arg]
            elif primary == DW_CFA_offset:
                args = [
                    primary_arg,
                    struct_parse(structs.Dwarf_uleb128(''), self.stream)]
            elif primary == DW_CFA_restore:
                args = [primary_arg]
            # primary == 0 and real opcode is extended
            elif opcode in (DW_CFA_nop, DW_CFA_remember_state,
                            DW_CFA_restore_state):
                args = []
            elif opcode == DW_CFA_set_loc:
                args = [
                    struct_parse(structs.Dwarf_target_addr(''), self.stream)]
            elif opcode == DW_CFA_advance_loc1:
                args = [struct_parse(structs.Dwarf_uint8(''), self.stream)]
            elif opcode == DW_CFA_advance_loc2:
                args = [struct_parse(structs.Dwarf_uint16(''), self.stream)]
            elif opcode == DW_CFA_advance_loc4:
                args = [struct_parse(structs.Dwarf_uint32(''), self.stream)]
            elif opcode in (DW_CFA_offset_extended, DW_CFA_register,
                            DW_CFA_def_cfa, DW_CFA_val_offset):
                args = [
                    struct_parse(structs.Dwarf_uleb128(''), self.stream),
                    struct_parse(structs.Dwarf_uleb128(''), self.stream)]
            elif opcode in (DW_CFA_restore_extended, DW_CFA_undefined,
                            DW_CFA_same_value, DW_CFA_def_cfa_register,
                            DW_CFA_def_cfa_offset):
                args = [struct_parse(structs.Dwarf_uleb128(''), self.stream)]
            elif opcode == DW_CFA_def_cfa_offset_sf:
                args = [struct_parse(structs.Dwarf_sleb128(''), self.stream)]
            elif opcode == DW_CFA_def_cfa_expression:
                args = [struct_parse(
                    structs.Dwarf_dw_form['DW_FORM_block'], self.stream)]
            elif opcode in (DW_CFA_expression, DW_CFA_val_expression):
                arsg = [
                    struct_parse(structs.Dwarf_uleb128(''), self.stream),
                    struct_parse(
                        structs.Dwarf_dw_form['DW_FORM_block'], self.stream)]
            elif opcode in (DW_CFA_offset_extended_sf,
                            DW_CFA_def_cfa_sf, DW_CFA_val_offset_sf):
                args = [
                    struct_parse(structs.Dwarf_uleb128(''), self.stream),
                    struct_parse(structs.Dwarf_sleb128(''), self.stream)]
            else:
                dwarf_assert(False, 'Unknown CFI opcode: 0x%x' % opcode)

            instructions.append(CallFrameInstruction(opcode=opcode, args=args))
            print instructions[-1]
            offset = self.stream.tell()
        return instructions


def instruction_name(opcode):
    """ Given an opcode, return the instruction name.
    """
    primary = opcode & _PRIMARY_MASK
    if primary == 0:
        return _OPCODE_NAME_MAP[opcode]
    else:
        return _OPCODE_NAME_MAP[primary]


#---------------- PRIVATE ----------------#

_PRIMARY_MASK = 0b11000000
_PRIMARY_ARG_MASK = 0b00111111

# This dictionary is filled by automatically scanning the constants module
# for DW_CFA_* instructions, and mapping their values to names. Since all
# names were imported from constants with `import *`, we look in globals()
_OPCODE_NAME_MAP = {}
for name in list(globals().iterkeys()):
    if name.startswith('DW_CFA'):
        _OPCODE_NAME_MAP[globals()[name]] = name



