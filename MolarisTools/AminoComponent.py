#-------------------------------------------------------------------------------
# . File      : AminoComponent.py
# . Program   : MolarisTools
# . Copyright : USC, Mikolaj Feliks (2016)
# . License   : GNU GPL v3.0       (http://www.gnu.org/licenses/gpl-3.0.en.html)
#-------------------------------------------------------------------------------
from    Utilities           import TokenizeLine
from    PDBFile             import PDBResidue, PDBAtom
from    EVBLibrary          import EVBLibrary
from    ParametersLibrary   import ParametersLibrary
from    GaussianOutputFile  import GaussianOutputFile
import  collections, exceptions, os, subprocess, math


AminoAtom  = collections.namedtuple ("Atom"  , "atomLabel  atomType  atomCharge")
AminoGroup = collections.namedtuple ("Group" , "natoms  centralAtom  radius  labels  symbol")

_MODULE_LABEL    = "AminoComponent"
_DEFAULT_DIVIDER = "-" * 41
_ATOMIC_SYMBOLS  = ("MG", "CL", "BR", )
_LINK_ATOM       = 1.09

_DEFAULT_GAUSSIAN_PATH  =  os.path.join (os.environ["HOME"], "local", "opt", "g03", "g03")
_DEFAULT_METHOD         =  "B3LYP/6-31G*"
_DEFAULT_SCHEME         =  "MERZKOLLMAN"
_DEFAULT_DIELECTRIC     =  78.4


class AminoComponent (object):
    """A class to represent a residue."""

    def __init__ (self, logging=True, **keywordArguments):
        """Constructor."""
        for (key, value) in keywordArguments.iteritems ():
            if key != "logging":
                setattr (self, key, value)
        # . Print info
        if logging: self.Info ()


    def Info (self):
        """Print info."""
        print ("Component: %d %s [%d atoms, %d bonds, %d groups, %-5.2f charge%s]" % (self.serial, self.name, self.natoms, self.nbonds, self.ngroups, self.charge, (", %s" % self.title if self.title != "" else "")))


    @property
    def natoms (self):
        if hasattr (self, "atoms"):
            return len (self.atoms)
        else:
            return 0

    @property
    def nbonds (self):
        if hasattr (self, "bonds"):
            return len (self.bonds)
        else:
            return 0

    @property
    def nangles (self):
        if hasattr (self, "angles"):
            return len (self.angles)
        else:
            return 0

    @property
    def ntorsions (self):
        if hasattr (self, "torsions"):
            return len (self.torsions)
        else:
            return 0

    @property
    def ngroups (self):
        if hasattr (self, "groups"):
            return len (self.groups)
        else:
            return 0

    @property
    def charge (self):
        if hasattr (self, "atoms"):
            total = 0.
            for atom in self.atoms:
                total += atom.atomCharge
            return total
        else:
            return 0.

    @property
    def label (self):
        if hasattr (self, "name"):
            return self.name
        return ""

    @label.setter
    def label (self, new):
        if hasattr (self, "name"):
            self.name = new


    def CalculateGroup (self, group):
        """Calculate the charge of a group."""
        total = 0.
        for atom in self.atoms:
            if atom.atomLabel in group.labels:
                total += atom.atomCharge
        return total


    _DEFAULT_MODIFY = {
        "A" :   ("O3",  "O-"),
        "B" :   ("O3",  "O-"),
        "C" :   ("O3",  "O-"),
        }
    def WriteDict (self, groups=None, nstates=2, modify=_DEFAULT_MODIFY):
        """Generate Python code to use in evb_assign.py type of script."""
        # . If no symbols defined, take the whole component
        groupSymbols = groups
        if groupSymbols is None:
            groupSymbols = []
            for group in self.groups:
                groupSymbols.append (group.symbol)
        # . Start here
        print ("names = {")
        for symbol in groupSymbols:
            # . Pick a group of atoms
            found = False
            for group in self.groups:
                if group.symbol == symbol:
                    found = True
                    break
            if not found:
                raise exceptions.StandardError ("Group %s not found." % symbol)
            # . Run for each atom in the group
            for label in group.labels:
                for atom in self.atoms:
                    if atom.atomLabel == label:
                        break
                atype   = atom.atomType
                # . Check if the atom type has to be modified
                if modify.has_key (symbol):
                    oldType, newType = modify[symbol]
                    if oldType == atype:
                        atype = newType
                    else:
                        atype = "%s0" % atype[0]
                else:
                    atype = "%s0" % atype[0]

                acharge = atom.atomCharge
                line    = "%-6s  :  (" % ("\"%s\"" % atom.atomLabel)
                # . For each atom, generate entries for n states
                for i in range (nstates):
                    if i > 0:
                        line = "%s  ,  (%5.2f , \"%2s\")" % (line, acharge, atype)
                    else:
                        line = "%s(%5.2f , \"%2s\")" % (line, acharge, atype)
                print ("%s) ," % line)
            # . Separate groups
            print ("\\")
        # . Finish up
        print ("}")


    def Write (self, filename=None, title=None, showGroups=False, showLabels=False, sortGroups=False, terminate=True):
        """Write component in a format understandable by Molaris."""
        output = []
        output.append (_DEFAULT_DIVIDER)
        # . Write header
        if title is None:
            if hasattr (self, "title"):
                title = self.title
        output.append ("%3d%s%s" % (self.serial, self.name, ("  ! %s" % title) if title else ""))

        # . Prepare a list of atoms
        atoms = self.atoms
        if sortGroups:
            atoms = []
            for group in self.groups:
                for atom in self.atoms:
                    if atom.atomLabel in group.labels:
                        atoms.append (atom)

        # . Prepare conversion table label->serial
        convert = {"" : 0, }
        for atomSerial, atom in enumerate (atoms, 1):
            convert[atom.atomLabel] = atomSerial

        # . Write atoms
        output.append ("%5d  ! Number of atoms" % self.natoms)
        for atom in atoms:
            markGroup = ""
            if showGroups:
                for igroup, group in enumerate (self.groups):
                    if atom.atomLabel in group.labels:
                        markGroup   = "  %s ! %s" % ("   " if (igroup % 2 == 1) else "", group.symbol)
                        break
            output.append ("%5d %-4s %4s %6.2f%s" % (convert[atom.atomLabel], atom.atomLabel, atom.atomType, atom.atomCharge, markGroup))

        # . Reorder bonds after sorting the groups
        bonds = self.bonds
        if sortGroups:
            # . Prepare serial bonds
            serialBonds = []
            for labela, labelb in self.bonds:
                seriala, serialb = convert[labela], convert[labelb]
                # . Keep the lower serial first
                if seriala > serialb:
                    seriala, serialb = serialb, seriala
                serialBonds.append ([seriala, serialb])
            # . Sort bonds
            serialBonds.sort (key=lambda bond: (bond[0], bond[1]))
            # . Invert the conversion table label->serial to serial->label
            trevnoc = {}
            for label, serial in convert.iteritems ():
                trevnoc[serial] = label
            # . Convert serial bonds to label bonds
            bonds = []
            for seriala, serialb in serialBonds:
                labela, labelb = trevnoc[seriala], trevnoc[serialb]
                pair = labela, labelb
                bonds.append (pair)
            # . We are done!

        # . Write bonds
        output.append ("%5d  ! Number of bonds" % self.nbonds)
        for labela, labelb in bonds:
            label = ""
            if showLabels:
                label = "%4s %4s" % (labela, labelb)
            output.append ("%5d%5d%s" % (convert[labela], convert[labelb], ("    ! %s" % label) if showLabels else ""))

        # . Write connecting atoms
        labela, labelb = self.connect
        clabels = ""
        if labela != "" or labelb != "":
            clabels = " (%s, %s)" % (labela, labelb)
        output.append ("%5d%5d  ! Connecting atoms%s" % (convert[labela], convert[labelb], clabels))

        # . Write groups
        output.append ("%5d  ! Number of electroneutral groups" % self.ngroups)
        totalCharge = 0.
        for group in self.groups:
            output.append ("%5d%5d%6.1f" % (group.natoms, convert[group.centralAtom], group.radius))
            # . Sort atoms in a group depending on their serial
            serials = []
            for atomLabel in group.labels:
                serials.append (convert[atomLabel])
            serials.sort ()
            # . Write serials of the group
            line = "    "
            for serial in serials:
                line = "%s%d  " % (line, serial)
            if showGroups:
                line = "%s  ! Group %s: %.4f" % (line, group.symbol, self.CalculateGroup (group))
                totalCharge += self.CalculateGroup (group)
            output.append (line)
        # . Finish up
        output.append ("%5d%s" % (0, "  ! Total charge: %.4f" % totalCharge if showGroups else ""))
        # . Make it the last component in the library
        if terminate:
            output.append (_DEFAULT_DIVIDER)
            output.append ("%5d" % 0)
            output.append (_DEFAULT_DIVIDER)
        # . Write to a file or terminal
        if filename:
            fo = open (filename, "w")
            for line in output:
                fo.write ("%s\n" % line)
            fo.close ()
        else:
            for line in output:
                print line


    def KillAtom (self, label, correctCharges=False):
        """Delete an atom from the component."""
        # . Remove from the list of atoms
        newAtoms   = []
        for atom in self.atoms:
            if not atom.atomLabel == label:
                newAtoms.append (atom)
            else:
                charge = atom.atomCharge
        if len (newAtoms) == len (self.atoms):
            raise exceptions.StandardError ("Atom %s not found." % label)
        self.atoms = newAtoms
        # . Add the charge of the killed atom to other charges in the same group
        if correctCharges:
            pass
        # . Remove bonds that include the killed atom
        newBonds   = []
        for labela, labelb in self.bonds:
            if not (labela == label or labelb == label):
                pair = (labela, labelb)
                newBonds.append (pair)
        self.bonds = newBonds
        # . Modify the group that includes the killed atom
        newGroups  = []
        for group in self.groups:
            labels     = []
            foundGroup = False
            for atomLabel in group.labels:
                if atomLabel == label:
                    foundGroup = True
                else:
                    labels.append (atomLabel)
            if foundGroup:
                if label == group.centralAtom:
                    centralAtom = labels[len (labels) / 2]
                else:
                    centralAtom = group.centralAtom
                newGroup = AminoGroup (natoms=(group.natoms - 1), centralAtom=centralAtom, radius=group.radius, labels=labels, symbol=group.symbol)
            else:
                newGroup = group
            newGroups.append (newGroup)
        self.groups = newGroups


    def KillBond (self, label, labelOther):
        """Delete a bond from the component."""
        pass


    def ReplaceAtom (self, label, newLabel, newType, newCharge):
        """Replace the label, type and charge of an atom."""
        # . Replace in the list of atoms
        found    = False
        newAtoms = []
        for atom in self.atoms:
            if atom.atomLabel == label:
                found = True
                atom  = AminoAtom (atomLabel=newLabel, atomType=newType, atomCharge=newCharge)
            newAtoms.append (atom)
        if not found:
            raise exceptions.StandardError ("Atom %s not found." % label)
        self.atoms = newAtoms

        # . Replace in the list of bonds
        newBonds = []
        for bonda, bondb in self.bonds:
            if   bonda == label:
                bonda = newLabel
            elif bondb == label:
                bondb = newLabel
            newBonds.append ((bonda, bondb))
        self.bonds = newBonds

        # . Replace in the group
        newGroups = []
        for group in self.groups:
            found     = False
            newLabels = []
            for atomLabel in group.labels:
                if atomLabel == label:
                    found     = True
                    atomLabel = newLabel
                newLabels.append (atomLabel)
            if found:
                newGroup = AminoGroup (natoms=group.natoms, centralAtom=group.centralAtom, radius=group.radius, labels=newLabels, symbol=group.symbol)
                group    = newGroup
            newGroups.append (group)
        self.groups = newGroups


    # . Convert atom types Enzymix -> CHARMM
    _DEFAULT_CONVERT_TYPE = {
        "P4"    :   "P2"    ,
        "O3"    :   "ON3"   ,
        "O4"    :   "ON2"   ,
        "H4"    :   "HN8"   ,
        "CT"    :   "CN8"   ,
        }
    def WriteToCHARMM (self, filename=None, convertTypes=_DEFAULT_CONVERT_TYPE):
        """Convert to CHARMM format."""
        output = []
        # . Write header
        output.append ("RESI %s    %.2f%s" % (self.name, self.charge, ("  ! %s" % self.title) if self.title else ""))
        # . Write groups of atoms
        for group in self.groups:
            output.append ("GROUP")
            groupCharge = 0.
            for iatom, atomLabel in enumerate (group.labels, 1):
                for atom in self.atoms:
                    if atom.atomLabel == atomLabel:
                        groupCharge += atom.atomCharge
                        atomType = atom.atomType
                        if convertTypes:
                            if convertTypes.has_key (atom.atomType):
                                atomType = convertTypes[atom.atomType]
                        groupSummary = ""
                        if iatom == len (group.labels):
                            groupSummary = "  ! Charge: %5.2f" % groupCharge
                        output.append ("ATOM %-4s %-4s    %5.2f%s" % (atom.atomLabel, atomType, atom.atomCharge, groupSummary))
                        break
            output.append ("!")
        # . Write bonds
        counter = 0
        line    = "BOND "
        for (bonda, bondb) in self.bonds:
            line = "%s %-4s %-4s    " % (line, bonda, bondb)
            counter += 1
            if counter > 4:
                output.append (line)
                counter = 0
                line    = "BOND "
        if line:
            output.append (line)
        output.append ("!")
        # . Write to a file or terminal
        if filename:
            fo = open (filename, "w")
            for line in output:
                fo.write ("%s\n" % line)
            fo.close ()
        else:
            for line in output:
                print line


    def GenerateAngles (self, logging=True):
        """Automatically generate a list of angles."""
        angles = []
        # . Outer loop
        for i, (bonda, bondb) in enumerate (self.bonds):
            # . Inner loop
            for j, (othera, otherb) in enumerate (self.bonds):
                if i != j:
                    angle = None
                    #   (a, b)
                    #      (c, d)
                    if   bondb == othera:
                        angle = (bonda, bondb, otherb)
                    #      (a, b)
                    #   (c, d)
                    elif bonda == otherb:
                        angle = (othera, bonda, bondb)
                    #   (a, b)
                    #      (d, c)
                    elif bondb == otherb:
                        angle = (bonda, bondb, othera)
                    #      (a, b)
                    #   (d, c)
                    elif bonda == othera:
                        angle = (otherb, bonda, bondb)
                    if angle:
                        (a, b, c) = angle
                        elgna = (c, b, a)
                        if (angle not in angles) and (elgna not in angles):
                            angles.append (angle)
        self.angles = angles
        if logging:
            print ("# . %s> Generated %d angles" % (_MODULE_LABEL, self.nangles))


    def GenerateTorsions (self, logging=True):
        """Automatically generate a list of torsions (=dihedral angles)."""
        if hasattr (self, "angles"):
            torsions = []
            # . Outer loop
            for i, (anglea, angleb, anglec) in enumerate (self.angles):
                # . Inner loop
                for j, (otherd, othere, otherf) in enumerate (self.angles):
                    if i != j:
                        torsion = None
                        #   (a, b, c)
                        #      (d, e, f)
                        if   (angleb == otherd) and (anglec == othere):
                            torsion = (anglea, angleb, anglec, otherf)
                        #      (a, b, c)
                        #   (d, e, f)
                        elif (anglea == othere) and (angleb == otherf):
                            torsion = (otherd, anglea, angleb, anglec)
                        #   (a, b, c)
                        #      (f, e, d)
                        elif (angleb == otherf) and (anglec == othere):
                            torsion = (anglea, angleb, anglec, otherd)
                        #      (a, b, c)
                        #   (f, e, d)
                        elif (anglea == othere) and (angleb == otherd):
                            torsion = (otherf, anglea, angleb, anglec)
                        if torsion:
                            (a, b, c, d) = torsion
                            noisrot = (d, c, b, a)
                            if (torsion not in torsions) and (noisrot not in torsions):
                                torsions.append (torsion)
            self.torsions = torsions
        if logging:
            print ("# . %s> Generated %d torsions" % (_MODULE_LABEL, self.ntorsions))


    def _BondsToTypes (self):
        types  = []
        for (bonda, bondb) in self.bonds:
            for atom in self.atoms:
                if   atom.atomLabel == bonda:
                    typea = atom.atomType
                elif atom.atomLabel == bondb:
                    typeb = atom.atomType
            pair = (typea, typeb)
            types.append (pair)
        unique = []
        for (typea, typeb) in types:
            if (typea, typeb) not in unique:
                if (typeb, typea) not in unique:
                    pair = (typea, typeb)
                    unique.append (pair)
        return (types, unique)


    def _AnglesToTypes (self):
        types  = []
        for (anglea, angleb, anglec) in self.angles:
            for atom in self.atoms:
                if   atom.atomLabel == anglea:
                    typea = atom.atomType
                elif atom.atomLabel == angleb:
                    typeb = atom.atomType
                elif atom.atomLabel == anglec:
                    typec = atom.atomType
            triplet = (typea, typeb, typec)
            types.append (triplet)
        unique = []
        for (typea, typeb, typec) in types:
            if (typea, typeb, typec) not in unique:
                if (typec, typeb, typea) not in unique:
                    triplet = (typea, typeb, typec)
                    unique.append (triplet)
        return (types, unique)


    def _TorsionsToTypes (self):
        types   = []
        for (torsiona, torsionb, torsionc, torsiond) in self.torsions:
            for atom in self.atoms:
                if   atom.atomLabel == torsiona:
                    typea = atom.atomType
                elif atom.atomLabel == torsionb:
                    typeb = atom.atomType
                elif atom.atomLabel == torsionc:
                    typec = atom.atomType
                elif atom.atomLabel == torsiond:
                    typed = atom.atomType
            quadruplet = (typea, typeb, typec, typed)
            types.append (quadruplet)
        unique  = []
        for (typea, typeb, typec, typed) in types:
            if (typea, typeb, typec, typed) not in unique:
                if (typed, typec, typeb, typea) not in unique:
                    quadruplet = (typea, typeb, typec, typed)
                    unique.append (quadruplet)
        general = []
        for (typea, typeb, typec, typed) in types:
            if (typeb, typec) not in general:
                if (typec, typeb) not in general:
                    pair = (typeb, typec)
                    general.append (pair)
        return (types, unique, general)


    def WriteTopology (self, writeTypes=False, filename=""):
        """Write object's bonds, angles and dihedrals."""
        lines = ["*** Bonds ***", ]
        bondTypes, bondUnique = self._BondsToTypes ()
        for i, ((bonda, bondb), (typea, typeb)) in enumerate (zip (self.bonds, bondTypes), 1):
            types = ""
            if writeTypes:
                types = " " * 10 + "# %-4s    %-4s" % (typea, typeb)
            lines.append ("%3d    %-4s    %-4s%s" % (i, bonda, bondb, types))
        
        if hasattr (self, "angles"):
            lines.append ("*** Angles ***")
            angleTypes, angleUnique = self._AnglesToTypes ()
            for i, ((anglea, angleb, anglec), (typea, typeb, typec)) in enumerate (zip (self.angles, angleTypes), 1):
                types = ""
                if writeTypes:
                    types = " " * 10 + "# %-4s    %-4s    %-4s" % (typea, typeb, typec)
                lines.append ("%3d    %-4s    %-4s    %-4s%s" % (i, anglea, angleb, anglec, types))

        if hasattr (self, "torsions"):
            lines.append ("*** Torsions ***")
            torsionTypes, torsionUnique, torsionGeneral = self._TorsionsToTypes ()
            for i, ((torsiona, torsionb, torsionc, torsiond), (typea, typeb, typec, typed)) in enumerate (zip (self.torsions, torsionTypes), 1):
                types = ""
                if writeTypes:
                    types = " " * 10 + "# %-4s    %-4s    %-4s    %-4s" % (typea, typeb, typec, typed)
                lines.append ("%3d    %-4s    %-4s    %-4s    %-4s%s" % (i, torsiona, torsionb, torsionc, torsiond, types))

            lines.append ("*** General torsions ***")
            general      = []
            generalTypes = []
            for (torsiona, torsionb, torsionc, torsiond), (typea, typeb, typec, typed) in zip (self.torsions, torsionTypes):
                pair = (torsionb, torsionc)
                reverse = (torsionc, torsionb)
                if (pair not in general) and (reverse not in general):
                    general.append (pair)
                    types = (typeb, typec)
                    generalTypes.append (types)
            for i, ((torsionb, torsionc), (typeb, typec)) in enumerate (zip (general, generalTypes), 1):
                types = ""
                if writeTypes:
                    types = " " * 10 + "# %-4s    %-4s    %-4s    %-4s" % ("@@", typeb, typec, "@@")
                lines.append ("%3d    %-4s    %-4s    %-4s    %-4s%s" % (i, "@@", torsionb, torsionc, "@@", types))

        if not filename:
            for line in lines:
                print line
        else:
            fo = open (filename, "w")
            for line in lines:
                fo.write (line + "\n")
            fo.close ()


    def WriteTypes (self, filename="", parameters=None, evbParameters=None):
        """Write object's types for bonds, angles and dihedrals."""
        includeParameters    = isinstance (parameters,    ParametersLibrary)
        includeEVBParameters = isinstance (evbParameters, EVBLibrary)

        lines = ["*** Bond types ***", ]
        bondTypes, bondUnique = self._BondsToTypes ()
        for i, (typea, typeb) in enumerate (bondUnique, 1):
            par = ""
            if includeParameters:
                bond = parameters.GetBond (typea, typeb)
                if bond:
                    par = "    %6.1f    %6.2f" % (bond.k, bond.r0)
            if includeEVBParameters:
                #
                # . FIXME: Enzymix types are different than EVB types.
                # . EVB type information must be somehow included in the amino library.
                #
                bond = evbParameters.GetBond (typea, typeb)
                if bond:
                    (morseD, r0) = bond
                    par = "%s    %6.1f    %6.2f" % (par, morseD, r0)
            lines.append ("%3d    %-4s    %-4s%s" % (i, typea, typeb, par))

        if hasattr (self, "angles"):
            lines.append ("*** Angle types ***")
            angleTypes, angleUnique = self._AnglesToTypes ()
            for i, (typea, typeb, typec) in enumerate (angleUnique, 1):
                par = ""
                if includeParameters:
                    angle = parameters.GetAngle (typea, typeb, typec)
                    if angle:
                        par = "    %6.1f    %6.2f" % (angle.k, angle.r0)
                if includeEVBParameters:
                    pass
                lines.append ("%3d    %-4s    %-4s    %-4s%s" % (i, typea, typeb, typec, par))

        if hasattr (self, "torsions"):
            lines.append ("*** Torsion types ***")
            torsionTypes, torsionUnique, torsionGeneral = self._TorsionsToTypes ()
            for i, (typea, typeb, typec, typed) in enumerate (torsionUnique, 1):
                par = ""
                if includeParameters:
                    torsion = parameters.GetTorsion (typeb, typec)
                    if torsion:
                        par = "    %1d    %6.2f    %6.1f" % (torsion.periodicity, torsion.k, torsion.phase)
                if includeEVBParameters:
                    pass
                lines.append ("%3d    %-4s    %-4s    %-4s    %-4s%s" % (i, typea, typeb, typec, typed, par))

            lines.append ("*** General torsion types ***")
            for i, (typeb, typec) in enumerate (torsionGeneral, 1):
                par = ""
                if includeParameters:
                    torsion = parameters.GetTorsion (typeb, typec)
                    if torsion:
                        par = "    %1d    %6.2f    %6.1f" % (torsion.periodicity, torsion.k, torsion.phase)
                if includeEVBParameters:
                    pass
                lines.append ("%3d    %-4s    %-4s    %-4s    %-4s%s" % (i, "@@", typeb, typec, "@@", par))

        lines.append ("*** Van der Waals and mass types ***")
        atomUnique = []
        for atom in self.atoms:
            if atom.atomType not in atomUnique:
                atomUnique.append (atom.atomType)
        for i, atomType in enumerate (atomUnique, 1):
            par = ""
            if includeParameters:
                vdw = parameters.GetVDW (atomType)
                if vdw:
                    par = "    %8.1f    %8.1f    %6.2f" % (vdw.repulsive, vdw.attractive, vdw.mass)
            if includeEVBParameters:
                pass
            lines.append ("%3d    %-4s%s" % (i, atomType, par))

        if not filename:
            for line in lines:
                print line
        else:
            fo = open (filename, "w")
            for line in lines:
                fo.write (line + "\n")
            fo.close ()


    def CalculateCharges (self, pdbResidue, ncpu=1, memory=1, charge=None, multiplicity=1, method=_DEFAULT_METHOD, scheme=_DEFAULT_SCHEME, cosmo=False, dielectric=_DEFAULT_DIELECTRIC, optimize=False, pathGaussian=_DEFAULT_GAUSSIAN_PATH, logging=True):
        """Calculate quantum chemical charges in Gaussian."""
    
        # . Do some initial checks
        if not isinstance (pdbResidue, PDBResidue):
            raise exceptions.StandardError ("Not a PDB residue.")
    
        if len (pdbResidue.atoms) != self.natoms:
            raise exceptions.StandardError ("Wrong number of atoms.")

        # . Collect atomic coordinates
        coordinates = []
        for atom in self.atoms:
            found = False
            for atomPDB in pdbResidue.atoms:
                if atom.atomLabel == atomPDB.label:
                    found = True
                    break
            if not found:
                raise exceptions.StandardError ("Atom %s not found in PDB file." % atom.atomLabel)
            coordinates.append (atomPDB)
    
        # . Prepare filenames
        fError       =  "job_%s.err" % self.label
        fInput       =  "job_%s.inp" % self.label
        fOutput      =  "job_%s.log" % self.label
        fCheckpoint  =  "job_%s.chk" % self.label
    
        lines   = []
        if ncpu > 1:
            lines.append ("%%NProcShared=%d\n" % ncpu)
        lines.append ("%%mem=%dgb\n" % memory)
        lines.append ("%%chk=%s\n"   % fCheckpoint)
        
        # . Set up a charge scheme
        convert = {
            "CHELPG"       :   "POP=CHELPG" ,
            "MULLIKEN"     :   ""           ,
            "MERZKOLLMAN"  :   "POP=MK"     , }
        if not convert.has_key (scheme):
            raise exceptions.StandardError ("Charge scheme %s is undefined." % scheme)
        chargeScheme = convert[scheme]
        
        # . Write header
        background = "SCRF=(Solvent=Water,Read)" if cosmo                        else ""
        restart    = "Guess=Read"                if os.path.exists (fCheckpoint) else ""
        # . Optimize geometry before calculating charges?
        opt        = "OPT"                       if optimize                     else ""
        keywords   = (method, "NoSymm", restart, background, chargeScheme, opt)
        header     = " ".join (keywords)
        lines.append ("#P " + header + "\n\n")
        lines.append ("Input file generated by MolarisTools.\n\n")
        # . Calculate the net charge from the sum of MM charges
        if charge is None:
            charge = 0.
            for group in self.groups:
                charge += self.CalculateGroup (group)
            if logging:
                print ("# . %s> Using a total charge of %.1f for component %s" % (_MODULE_LABEL, charge, self.label))
        totalCharge = int (round (charge))
        lines.append ("%d %d\n" % (totalCharge, multiplicity))

        # . Write geometry
        for atom in coordinates:
            atomSymbol = atom.label[0]
            for symbol in _ATOMIC_SYMBOLS:
                if atom.label.startswith (symbol):
                    atomSymbol = symbol
                    break
            lines.append ("%2s    %16.10f    %16.10f    %16.10f\n" % (atomSymbol, atom.x, atom.y, atom.z))
        lines.append ("\n")
        
        # . If cosmo=True, write epsilon
        if cosmo:
            lines.append ("eps=%f\n\n" % dielectric)
    
        # . Run when there is no output file    
        if not os.path.exists (fOutput):
            if logging:
                print ("# . %s> Now running charge calculation for %s ..." % (_MODULE_LABEL, self.label))
            fi = open (fInput, "w")
            for line in lines:
                fi.write (line)
            fi.close ()
            fe = open (fError, "w")
            subprocess.check_call ([pathGaussian, fInput], stdout=fe, stderr=fe)
            fe.close ()
    
        # . Read Gaussian putput file
        gaussian = GaussianOutputFile (fOutput)
    
        # . Assign charges to amino component
        convert = {
            "MULLIKEN"     :  gaussian.charges      ,
            "MERZKOLLMAN"  :  gaussian.espcharges   ,
            "CHELPG"       :  gaussian.espcharges   , }
        charges = convert[scheme]
        # . Update charges in atoms
        newAtoms = []
        for atom, charge in zip (self.atoms, charges):
            newAtom = AminoAtom (
                atomLabel   =   atom.atomLabel  ,
                atomType    =   atom.atomType   ,
                atomCharge  =   charge          ,
                )
            newAtoms.append (newAtom)
        self.atoms = newAtoms
        # . Create one group of atoms
        labels = []
        for atom in newAtoms:
            labels.append (atom.atomLabel)
        natoms = len (newAtoms)
        aminoGroup = AminoGroup (
            radius      =   5.       ,
            natoms      =   natoms   ,
            labels      =   labels   ,
            symbol      =   self.groups[0].symbol           ,
            centralAtom =   newAtoms[natoms / 2].atomLabel  ,
            )
        self.groups = [aminoGroup, ]

        # . Finish up
        if logging:
            print ("# . %s> Setting quantum charges to %s complete" % (_MODULE_LABEL, self.label))


    def CalculateChargesGroups (self, pdbResidue, ncpu=1, memory=1, method=_DEFAULT_METHOD, scheme=_DEFAULT_SCHEME, cosmo=False, dielectric=_DEFAULT_DIELECTRIC, optimize=False, pathGaussian=_DEFAULT_GAUSSIAN_PATH, logging=True):
        """Correct charges in Gaussian while keeping charge groups unchanged."""
    
        # . Do some initial checks
        if not isinstance (pdbResidue, PDBResidue):
            raise exceptions.StandardError ("Not a PDB residue.")
    
        if len (pdbResidue.atoms) != self.natoms:
            raise exceptions.StandardError ("Wrong number of atoms.")

        # . Collect atomic coordinates
        coordinates = []
        for atom in self.atoms:
            found = False
            for atomPDB in pdbResidue.atoms:
                if atom.atomLabel == atomPDB.label:
                    found = True
                    break
            if not found:
                raise exceptions.StandardError ("Atom %s not found in PDB file." % atom.atomLabel)
            coordinates.append (atomPDB)

        # . Iterate groups
        results = []
        for group in self.groups:
            # . Prepare filenames
            fError       =  "job_%s_%s.err" % (self.label, group.symbol)
            fInput       =  "job_%s_%s.inp" % (self.label, group.symbol)
            fOutput      =  "job_%s_%s.log" % (self.label, group.symbol)
            fCheckpoint  =  "job_%s_%s.chk" % (self.label, group.symbol)

            # . Calculate the charge of the group
            charge       = self.CalculateGroup (group)
            if logging:
                print ("# . %s> Group %s in component %s has a charge of %.1f" % (_MODULE_LABEL, group.symbol, self.label, charge))
            groupCharge  = int (round (charge))

            lines   = []
            if ncpu > 1:
                lines.append ("%%NProcShared=%d\n" % ncpu)
            lines.append ("%%mem=%dgb\n" % memory)
            lines.append ("%%chk=%s\n"   % fCheckpoint)
            
            # . Set up a charge scheme
            convert = {
                "CHELPG"       :   "POP=CHELPG" ,
                "MULLIKEN"     :   ""           ,
                "MERZKOLLMAN"  :   "POP=MK"     , }
            if not convert.has_key (scheme):
                raise exceptions.StandardError ("Charge scheme %s is undefined." % scheme)
            chargeScheme = convert[scheme]
            
            # . Write header
            background   = "SCRF=(Solvent=Water,Read)" if cosmo                        else ""
            restart      = "Guess=Read"                if os.path.exists (fCheckpoint) else ""
            # . Optimize geometry before calculating charges?
            opt          = "OPT"                       if optimize                     else ""
            keywords     = (method, "NoSymm", restart, background, chargeScheme, opt)
            header       = " ".join (keywords)
            lines.append ("#P " + header + "\n\n")
            lines.append ("Input file generated by MolarisTools.\n\n")
            multiplicity = 1
            lines.append ("%d %d\n" % (groupCharge, multiplicity))
    
            # . Write geometry
            for atom in coordinates:
                if atom.label in group.labels:
                    atomSymbol = atom.label[0]
                    for symbol in _ATOMIC_SYMBOLS:
                        if atom.label.startswith (symbol):
                            atomSymbol = symbol
                            break
                    lines.append ("%2s    %16.10f    %16.10f    %16.10f\n" % (atomSymbol, atom.x, atom.y, atom.z))

            # . Determine and add "link" atoms
            links = []
            for (labela, labelb) in self.bonds:
                linkFound = False
                flip      = False
                if   (labela     in group.labels) and (labelb not in group.labels):
                    linkFound = True
                elif (labela not in group.labels) and (labelb     in group.labels):
                    linkFound = True
                    flip      = True
                if linkFound:
                    # . Make atom "b" always the one that sticks out from the group
                    if flip:
                        labela, labelb = labelb, labela
                    for atomPDB in coordinates:
                        if   atomPDB.label == labela:
                            atoma = atomPDB
                        elif atomPDB.label == labelb:
                            atomb = atomPDB
                    vx  = atomb.x - atoma.x
                    vy  = atomb.y - atoma.y
                    vz  = atomb.z - atoma.z
                    vl  = math.sqrt (vx ** 2 + vy ** 2 + vz ** 2)
                    vx /= vl
                    vy /= vl
                    vz /= vl
                    linkAtom = PDBAtom (
                        label   =   "H" ,
                        serial  =   0   ,
                        x       =   atoma.x + vx * _LINK_ATOM   ,
                        y       =   atoma.y + vy * _LINK_ATOM   , 
                        z       =   atoma.z + vz * _LINK_ATOM   , )
                    links.append (linkAtom)
            for atom in links:
                lines.append ("%2s    %16.10f    %16.10f    %16.10f\n" % (atom.label, atom.x, atom.y, atom.z))
            lines.append ("\n")
            
            # . If cosmo=True, write epsilon
            if cosmo:
                lines.append ("eps=%f\n\n" % dielectric)
        
            # . Run when there is no output file    
            if not os.path.exists (fOutput):
                if logging:
                    print ("# . %s> Now running charge calculation for %s, group %s, group charge=%d ..." % (_MODULE_LABEL, self.label, group.symbol, groupCharge))
                fi = open (fInput, "w")
                for line in lines:
                    fi.write (line)
                fi.close ()
                fe = open (fError, "w")
                subprocess.check_call ([pathGaussian, fInput], stdout=fe, stderr=fe)
                fe.close ()

            # . Read Gaussian putput file
            gaussian = GaussianOutputFile (fOutput)

            # . Collect charges from Gaussian
            convert = {
                "MULLIKEN"     :  gaussian.charges      ,
                "MERZKOLLMAN"  :  gaussian.espcharges   ,
                "CHELPG"       :  gaussian.espcharges   , }
            charges = convert[scheme]

            # . Add the charges of link atoms to non-link atoms
            nlinks   = len (links)
            natoms   = len (group.labels)
            correct  = 0.
            if nlinks > 0:
                correct = sum (charges[natoms:])
            correct /= natoms
            corrCharges = []
            for charge in charges[:natoms]:
                corrCharges.append (charge + correct)
            if logging:
                total = sum (charges[:natoms])
                totalLink = sum (charges[natoms:])
                print ("# . %s> Component %s, group %s charge %f, link atom correction %f" % (_MODULE_LABEL, self.label, group.symbol, total, totalLink))

            # . Save and go to a next group
            results.append (corrCharges)

        # . Finally, assign calculated charges to atoms
        newAtoms = []
        for atom in self.atoms:
            for (group, charges) in zip (self.groups, results):
                if atom.atomLabel in group.labels:
                    index = group.labels.index (atom.atomLabel)
                    break
            charge  = charges[index]
            newAtom = AminoAtom (
                atomLabel   =   atom.atomLabel  ,
                atomType    =   atom.atomType   ,
                atomCharge  =   charge          ,
                )
            newAtoms.append (newAtom)
        self.atoms = newAtoms

        # . Print a summary
        if logging:
            print ("# . %s> Setting quantum charges to %s complete" % (_MODULE_LABEL, self.label))


#===============================================================================
# . Main program
#===============================================================================
if __name__ == "__main__": pass