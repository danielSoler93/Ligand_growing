import prody
import Bio.PDB as bio
import logging
import numpy as np
import re
import sys


# Getting the name of the module for the log system
logger = logging.getLogger(__name__)


def get_ligand_from_PDB(pdb_file):
    """
    :param pdb_file: PDB file with only the ligand
    :return: Bio.PDB object of the input PDB
    """
    parser = bio.PDBParser()
    structure = parser.get_structure("structure", pdb_file)
    return structure


def get_atoms_from_structure(structure):
    """
    :param structure: Bio.PDB object of the input PDB
    :return: list with the atoms that form the input structure
    """
    atom_list = []
    for atom in structure.get_atoms():
        atom_list.append(atom)
    return atom_list


def select_atoms_from_list(PDB_atom_name, atoms_list):
    """
    Given a pdb atom name string and a list of atoms (BioPython Atom) it returns the Bio.Atom correspondent to the atom
    name.
    :param PDB_atom_name: string with an atom name
    :param atoms_list: list of Bio.Atoms
    :return: Bio.Atom correspondent to the atom name
    """
    for atom in atoms_list:
        if atom.name == PDB_atom_name:
            return atom


def get_H_bonded_to_grow(PDB_atom_name, prody_complex):
    """
    Given a heavy atom name (string) and a complex (prody molecule) it returns the hydrogen atom of the chain L
    placed at bonding distance of the input atom name. If there is more than one, a checking of contacts with the
    protein will be performed. In case of finding a possible contact between the hydrogen and the protein, we will
    reject this hydrogen and we will repeat the check in another one. If all the hydrogens have contacts with the
    protein, the first of them will be selected and a warning will be printed.
    :param PDB_atom_name: heavy atom name (string) of a ligand
    :param prody_complex: prody molecule object
    :return: hydrogen atom of the ligand placed at bonding distance of the heavy atom
    """
    # Select the hydrogens bonded to the heavy atom 'PDB_atom_name'
    selected_h = prody_complex.select("chain L and hydrogen within 1.5 of name {}".format(PDB_atom_name))
    # In case that we found more than one we have to select one of them
    try:
        number_of_h = len(selected_h)
    except TypeError:
        raise TypeError("Check either core or fragment atom to bound when passing parameters")
    if len(selected_h) > 1:
        for idx, hydrogen in enumerate(selected_h):
            # We will select atoms of the protein in interaction distance
            select_h_bonds = prody_complex.select("protein and within 2.5 of (name {} and chain L)"
                                                  .format(selected_h.getNames()[idx]))
            if select_h_bonds is not None:
                logger.warning("WARNING: {} is forming a close interaction with the protein! We will try to grow"
                               " in another direction.".format(selected_h.getNames()[idx]))
            # We put this elif to select one of H randomly if all of them have contacts
            elif (select_h_bonds is not None) and (idx == len(selected_h) -1):
                hydrogen_pdbatomname = selected_h.getNames()[0]
                return hydrogen_pdbatomname
            else:
                hydrogen_pdbatomname = selected_h.getNames()[idx]
                return hydrogen_pdbatomname
    else:
        hydrogen_pdbatomname = selected_h.getNames()
        return hydrogen_pdbatomname


# This function is prepared to rename PDB atom names of the repeated names, but is not working currently
def change_repeated_atomnames(list_of_repeated_names, core_names):
    list_of_lists_repeated = []
    for atom in list_of_repeated_names:
        find_name_and_number = re.search('([A-Z]*)([0-9]*)', atom)
        element = find_name_and_number.group(1)
        number = find_name_and_number.group(2)
        list_of_lists_repeated.append([element, number])
    list_of_lists_core = []
    for atom in core_names:
        find_name_and_number = re.search('([A-Z]*)([0-9]*)', atom)
        element = find_name_and_number.group(1)
        number = find_name_and_number.group(2)
        list_of_lists_core.append([element, number])
    for repeated_atom in list_of_lists_repeated:
        for core_atom in list_of_lists_core:
            if repeated_atom[0] is core_atom[0]:
                new_name = [repeated_atom[0], int(repeated_atom[1]) + 1]
                new_name = [new_name[0], str(new_name[1])]
                switch = False
                while not switch:
                    if new_name not in list_of_lists_core:
                        list_of_lists_core.append(new_name)
                        switch = True
                    new_name = [new_name[0], int(new_name[1])+1]
                    new_name = [new_name[0], str(new_name[1])]


def superimpose(fixed_vector, moving_vector, moving_atom_list):
    """
    Rotates and translates a list of moving atoms from a moving vector to a fixed vector.
    :param fixed_vector: vector used as reference.
    :param moving_vector: vector that will rotate and translate.
    :param moving_atom_list: list of atoms that we want to do the rotation and translation of the moving vector.
    :return: the input list of atoms is rotated an translated.
    """
    # Do the superimposition with BioPython
    sup = bio.Superimposer()
    # Set the vectors: first element is the fix vector (bond of the core) and second is the moving (bond of the fragment)
    sup.set_atoms(fixed_vector, moving_vector)
    # Apply the transformation to the atoms of the fragment (translate and rotate)
    return sup.apply(moving_atom_list)


def transform_coords(atoms_with_coords):
    """
    Transform the coords of a molecule (ProDy selection) into the coords from a list of atoms of Bio.PDB.
    :param atoms_with_coords: list of atoms (from a Bio.PDB) with the coordinates that we want to set.
    :return: perform the transformation of the coords.
    """
    coords = []
    for atom in atoms_with_coords:
        coords.append(list(atom.get_coord()))
    return np.asarray(coords)


def extract_and_change_atomnames(molecule, selected_resname):
    """
    Given a ProDy molecule and a Resname this function will rename the PDB atom names for the selected residue following
    the next pattern: G1, G2, G3...
    :param molecule: ProDy molecule.
    :param selected_resname: Residue name whose atoms you would like to rename.
    :return: ProDy molecule with atoms renamed and dictionary {"original atom name" : "new atom name"}
    """
    selection_to_change = molecule.select("resname {}".format(selected_resname))
    names_dictionary = {}
    for n, atomname in enumerate(selection_to_change.getNames()):
        names_dictionary[atomname] = "G{}".format(n)
    for atom in molecule:
        if atom.getResname() == selected_resname:
            atom.setName(names_dictionary[atom.getName()])
    return molecule, names_dictionary


def check_overlapping_names(structures_to_bond):
    """
    Checking that there is not duplications in the names of the structure. If not, it will return None, else, it will
    return the repeated elements.
    :param structures_to_bond: ProDy molecule
    :return: set object with the repeated elements if they are found. Else, None object.
    """
    all_atom_names = list(structures_to_bond.getNames())
    return set([name for name in all_atom_names if all_atom_names.count(name) > 1])




