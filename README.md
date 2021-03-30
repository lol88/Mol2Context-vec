# Mol2Context-vec
Mol2Context-vec:Learning molecular representation from context awareness for drug discovery

Mol2Context-vec provides a deep context aware molecular representation to drive the boundaries for drug discovery. It can integrate different levels of internal states to bring abundant molecular structure information.


Mol2Context-vec provides dynamic substructure representations to capture the local effects of the same substructure in different molecules. For substructures with ambiguity, the context vector generated by Mol2Context-vec correctly separates the different categories in the 3D space.

# Requirements 
```
PyTorch >= 1.2.0
Numpy >=1.19.2
mol2vec
```

# Usage example

**train Mol2Context-vec**
Corpus generation using 9M compounds in the ZINC database with replacement of uncommon identifiers. It generates morgan identifiers (up to selected radius) which represent words (molecules are sentences). Words are ordered in the sentence according to atom order in canonical SMILES (generated when generating corpus) and at each atom starting by identifier at radius 1.
```
mol2vec corpus -i mols.smi -o mols.cp -r 1 -j 4 --uncommon UNK --threshold 3
python split.py
python train.py
```

**For ESOL dataset**
```
python get_data.py

python esol_train.py
```
