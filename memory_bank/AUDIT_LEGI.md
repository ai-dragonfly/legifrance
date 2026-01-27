# Audit Technique du Corpus LEGI

**Date** : 21 Janvier 2026
**Source** : Archives Open Data DILA (Freemium)
**Format** : Tarball XML (`.tar.gz`)

## 1. Vue d'ensemble

Le corpus LEGI contient l'intégralité des codes juridiques français ainsi que les textes non codifiés (TNC) consolidés.

### Volumétrie (Mesurée)
*   **Taille Archive** : 1.1 Go (compressé GZIP).
*   **Nombre de Textes** : 144,551 (Codes + Accords/Conventions).
*   **Nombre d'Articles** : ~1,750,000 versions d'articles.
*   **Nombre de Sections** : ~236,000 nœuds de structure.

### Organisation Physique
L'archive est structurée en deux branches principales :
1.  `legi/global/code_et_TNC_en_vigueur/` : Textes applicables.
2.  `legi/global/code_et_TNC_non_vigueur/` : Textes abrogés.

## 2. Structure Interne d'un Code

Chaque entité (Code ou TNC) est identifiée par un ID unique (ex: `LEGITEXT000005634379` pour le Code de commerce).

### A. Le Conteneur (`LEGITEXT...`)
Chaque code dispose d'un répertoire propre contenant :
*   `texte/version/` : Fichier XML unique définissant les métadonnées globales (Titre, Dates de validité, État).
*   `texte/struct/` : Fichier XML définissant la **racine** de l'arborescence (Pointeurs vers les Livres/Parties).
*   `section_ta/` : Dossier contenant la hiérarchie récursive.
*   `article/` : Dossier contenant le texte des articles.

### B. La Hiérarchie (`section_ta`)
Le plan du code est découpé en "Sections Tableaux d'Affichage" (SCTA).
*   Chaque fichier XML (`LEGISCTA...`) représente un nœud (Livre, Titre, Chapitre).
*   Il contient une liste d'enfants :
    *   `<LIEN_SECTION_TA>` : Lien vers une sous-section (récursion).
    *   `<LIEN_ART>` : Lien vers un article (feuille de l'arbre).

### C. L'Article (`article`)
L'article est l'unité atomique.
*   **Format** : XML contenant du HTML (balises `<p>`, `<table>`).
*   **Versioning** : Chaque fichier XML correspond à **une version temporelle** d'un article.
    *   Si l'article L123 change, un nouveau fichier XML (nouvel ID `LEGIARTI...`) est créé.
    *   Les dates de validité sont définies par `DATE_DEBUT` et `DATE_FIN` (souvent `2999-01-01` pour "toujours en vigueur").
*   **Liens** : Le bloc `<LIENS>` contient les références sémantiques (Citation, Modification, Abrogation) vers d'autres textes.

## 3. Analyse Critique & Exploitation

### Points de Vigilance
1.  **Absence d'Index Global** : Il n'existe pas de fichier "Table des Matières" à la racine. Il faut scanner l'intégralité de l'archive pour lister les codes.
2.  **Profondeur** : L'arborescence peut être très profonde (jusqu'à 10 niveaux). Une exploration récursive naïve est coûteuse.
3.  **Texte Riche** : Le contenu des articles n'est pas du texte brut mais du HTML/XML riche. Il nécessite un parsing (`lxml`) pour être affiché proprement.

### Stratégie Technique Retenue (V2)
Pour rendre ce corpus exploitable par une IA ou une application moderne, nous avons mis en place :

1.  **Extraction Disque (`data/`)** :
    *   L'archive `.tar.gz` est décompressée une fois pour toutes dans le dossier `data/`.
    *   Cela permet un accès fichier aléatoire immédiat (< 1ms) sans parcourir l'archive séquentiellement.

2.  **Indexation SQL** :
    *   Aplatissement de la structure XML dans une base SQLite relationnelle.
    *   Permet des requêtes instantanées (ex: "Trouver tous les articles du Code de Commerce modifiés en 2024").

3.  **Précalcul** :
    *   Les "sommaires" (arborescences complètes) sont pré-générés en JSON compressé pour éviter de recalculer les milliers de jointures SQL à chaque requête.

Cette architecture permet de répondre en **< 100ms** là où une lecture directe du XML compressé prendrait plusieurs minutes.
