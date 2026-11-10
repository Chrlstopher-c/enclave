/*
 * Assemblage d'une `CibleChargement` à partir de trois domaines : `models` (ce que le fichier
 * contient), `system` (ce que la machine offre) et `engines` (quels moteurs sont réellement
 * utilisables).
 *
 * Ce module vit à la racine et non dans un domaine, parce qu'il est le seul endroit autorisé à en
 * connaître trois à la fois. Le mettre dans `chat` obligerait le chat à lire des en-têtes GGUF ;
 * dans `models`, à mesurer la machine. `chat/plan/cible.ts` l'énonce déjà comme contrat.
 *
 * Règle qui gouverne tout le fichier : **ce qui n'a pas été lu ne s'invente pas**. Une métadonnée
 * absente produit un refus nommé, pas une valeur par défaut. C'est la différence de fond avec la
 * v1, qui dérivait un contexte et une VRAM du nom d'un dépôt et se trompait sur les trois.
 *
 * Fonctions pures : aucun appel réseau ici, donc testables sans backend et sans GPU.
 */

/*
 * Les types du PLAN viennent de `chat` et non de `shared/api`, bien que les deux les déclarent :
 * `chat/api/contrats.ts` et `shared/api/types-plan.ts` sont deux transcriptions du même contrat
 * pydantic, écrites en parallèle, et elles divergent déjà (`dimension_tete` y est optionnel d'un
 * côté, nullable de l'autre). Produire ceux du consommateur est la seule façon de ne pas propager
 * l'écart. Cette duplication est une dette à résorber en amont, pas ici.
 */
import type {
  CibleChargement,
  MetadonneesModele,
  ModeleCharge,
  Moteur,
  PlateformePlan,
  ProfilMachinePlan,
} from '../chat';
import type {
  EtatMoteurs,
  MetadonneesGGUF,
  MetadonneesSafetensors,
  ModeleEnregistre,
  ProfilMachine,
  StatutInference,
} from '../shared/api';

/** Refus explicite : ce qui manque, et ce que l'utilisateur peut y faire. */
export interface RefusCible {
  readonly manquant: string;
  readonly remediation: string;
}

export type ResultatCible = { readonly cible: CibleChargement } | { readonly refus: RefusCible };

/*
 * La remédiation doit désigner une action qui EXISTE. La version précédente renvoyait à un bouton
 * « Vérifier » qui n'a jamais été posé dans l'interface : un conseil impossible à suivre est pire
 * qu'aucun conseil, il fait chercher une issue là où il n'y en a pas.
 *
 * Ce qui est dit ici est vrai de tous les cas rencontrés : l'en-tête ne porte pas la clé, ce n'est
 * ni un téléchargement raté ni un fichier abîmé, et aucune manipulation locale n'y changera rien.
 */
const REMEDIATION_METADONNEES =
  "Cette architecture ne déclare pas cette valeur dans son en-tête — le fichier n'est pas en cause. " +
  'Le clic droit sur le modèle donne son rapport de cohérence, qui détaille ce qui manque.';

/** Plateformes que le planificateur sait traiter. macOS et « inconnue » n'en font pas partie. */
const PLATEFORMES_PLANIFIABLES: readonly PlateformePlan[] = ['linux_natif', 'wsl2', 'windows'];

function estPlanifiable(plateforme: string): plateforme is PlateformePlan {
  return (PLATEFORMES_PLANIFIABLES as readonly string[]).includes(plateforme);
}

/** Moteurs dont la sonde a réellement réussi — « installé » ne suffit pas, la v1 confondait les deux. */
export function moteursUtilisables(moteurs: EtatMoteurs | null): Moteur[] {
  if (moteurs === null) {
    return [];
  }
  const disponibles: Moteur[] = [];
  if (moteurs.llamacpp.fonctionnel) disponibles.push('llama.cpp');
  if (moteurs.vllm.fonctionnel) disponibles.push('vllm');
  return disponibles;
}

/**
 * Modèle occupant le GPU, s'il y en a un. Le planificateur en a besoin pour décider d'une éjection :
 * le GPU est exclusif, et un chargement qui l'ignore échoue sur une VRAM déjà prise.
 */
export function modelesCharges(statut: StatutInference | null): ModeleCharge[] {
  const moteur = statut?.etat_moteur;
  if (statut === null || statut.etat !== 'pret' || moteur === null || moteur === undefined) {
    return [];
  }
  return [
    {
      identifiant: moteur.modele,
      moteur: moteur.moteur,
      // La DIFFÉRENCE entre les deux mesures, et non `vram_apres` seule.
      //
      // `vram_apres_octets` est la VRAM totale UTILISÉE de la carte, bureau compris — pas celle du
      // modèle. La passer telle quelle disait au planificateur qu'éjecter ce modèle rendrait aussi
      // les 1 453 Mio du compositeur, du shell et du navigateur. Il visait alors les 12 288 Mio de
      // la carte entière, ne déportait que 2 groupes d'experts, et le GPU refusait l'allocation :
      // le modèle est devenu inchargeable depuis cet écran, à TOUS les contextes, le 2026-08-26.
      //
      // `vram_avant` est mesurée juste avant le chargement : la soustraction isole le modèle. Sans
      // elle, on retombe sur `vram_apres` — donc sur le défaut.
      vram_octets: Math.max(0, (moteur.vram_apres_octets ?? 0) - (moteur.vram_avant_octets ?? 0)),
    },
  ];
}

export function versProfilPlan(
  profil: ProfilMachine,
  moteurs: EtatMoteurs | null,
  statut: StatutInference | null,
): ProfilMachinePlan | RefusCible {
  const gpu = profil.gpu_principal;
  if (gpu === null) {
    return { manquant: 'aucun GPU mesuré', remediation: "Vérifier l'exposition du GPU au conteneur." };
  }
  if (!estPlanifiable(profil.plateforme)) {
    return {
      manquant: `plateforme « ${profil.plateforme} » hors du champ du planificateur`,
      remediation: 'Exécuter EchoHub sous Linux natif, WSL2 ou Windows.',
    };
  }
  const majeur = gpu.compute_majeur;
  const mineur = gpu.compute_mineur;
  return {
    plateforme: profil.plateforme,
    index_gpu: gpu.index,
    nom_gpu: gpu.nom,
    vram_totale_octets: profil.vram_totale_octets,
    vram_libre_octets: profil.vram_libre_octets,
    ram_libre_octets: profil.ram_disponible_octets,
    moteurs_disponibles: moteursUtilisables(moteurs),
    modeles_charges: modelesCharges(statut),
    capacite_calcul: majeur === null || mineur === null ? null : [majeur, mineur],
  };
}

/** Les seuls champs sans lesquels aucun plan n'est calculable — tous doivent être LUS. */
interface ChampsRequis {
  nombre_couches: number;
  dimension_embedding: number;
  dimension_ffn: number;
  nombre_tetes_attention: number;
  contexte_entrainement_max: number;
  taille_vocabulaire: number;
  taille_octets: number;
}

/** Champ requis absent ou nul : on nomme lequel plutôt que de livrer un plan bâti sur du vide. */
function exiger(valeur: number | null | undefined, nom: string, source = "l'en-tête GGUF"): number | RefusCible {
  if (valeur === null || valeur === undefined || valeur <= 0) {
    return { manquant: `${nom} absent de ${source}`, remediation: REMEDIATION_METADONNEES };
  }
  return valeur;
}

function estRefus(valeur: number | RefusCible): valeur is RefusCible {
  return typeof valeur !== 'number';
}

export function versMetadonneesPlan(
  modele: ModeleEnregistre,
  gguf: MetadonneesGGUF | null,
): MetadonneesModele | RefusCible {
  if (gguf === null) {
    return {
      manquant: `métadonnées illisibles pour ${modele.id}`,
      remediation:
        modele.format === 'gguf'
          ? REMEDIATION_METADONNEES
          : "Le planificateur n'accepte aujourd'hui que des modèles GGUF.",
    };
  }
  const requis: Record<keyof ChampsRequis, number | RefusCible> = {
    nombre_couches: exiger(gguf.block_count, 'nombre de couches'),
    dimension_embedding: exiger(gguf.longueur_embedding, "dimension d'embedding"),
    // `largeur_ffn_active`, pas `longueur_feed_forward` : cette dernière n'existe pas sur les
    // architectures MoE, qui déclarent la largeur d'UN expert. Le backend fait la somme réelle
    // (experts routés + branche partagée) et la sérialise ; l'exiger ici bloquait tout MoE.
    dimension_ffn: exiger(gguf.largeur_ffn_active, 'dimension FFN'),
    nombre_tetes_attention: exiger(gguf.attention.nb_tetes, "nombre de têtes d'attention"),
    contexte_entrainement_max: exiger(gguf.contexte_natif, "contexte d'entraînement"),
    taille_vocabulaire: exiger(gguf.taille_vocabulaire, 'taille du vocabulaire'),
    taille_octets: exiger(modele.taille_octets, 'taille du fichier'),
  };
  for (const valeur of Object.values(requis)) {
    if (estRefus(valeur)) {
      return valeur;
    }
  }
  // Cast justifié : la boucle qui précède a rendu tout refus, il ne reste que des nombres. Le
  // typage ne peut pas suivre un narrowing porté par une itération sur les valeurs.
  return assembler(modele, gguf, requis as ChampsRequis);
}

/*
 * Mesures par bloc, transmises seulement si elles sont COMPLÈTES.
 *
 * `MetadonneesModele._verifier_mesures_par_bloc` refuse côté backend une mesure dont la longueur ne
 * fait pas `nombre_couches` — et il a raison de le faire : une mesure tronquée se lirait comme un
 * modèle plus léger qu'il n'est, et le plan qui en sortirait tiendrait sur le papier sans tenir en
 * VRAM. Ici, incomplet vaut absent : le planificateur retombe alors sur la coupe par couches, ce
 * qu'il sait faire et qu'il explique dans ses justifications.
 */
function mesuresParBloc(
  gguf: MetadonneesGGUF,
  nombreCouches: number,
): Pick<MetadonneesModele, 'octets_par_bloc' | 'octets_experts_par_bloc' | 'octets_hors_blocs'> {
  const mesures = gguf.mesures;
  if (mesures === null) {
    return {};
  }
  const totaux = mesures.octets_par_bloc;
  const experts = mesures.octets_experts_par_bloc;
  if (totaux.length !== nombreCouches || experts.length !== nombreCouches) {
    return {};
  }
  return {
    octets_par_bloc: totaux,
    octets_experts_par_bloc: experts,
    octets_hors_blocs: mesures.octets_hors_blocs,
  };
}

function assembler(modele: ModeleEnregistre, gguf: MetadonneesGGUF, requis: ChampsRequis): MetadonneesModele {
  return {
    identifiant: modele.id,
    format: modele.format,
    architecture: gguf.architecture,
    taille_octets: requis.taille_octets,
    nombre_couches: requis.nombre_couches,
    dimension_embedding: requis.dimension_embedding,
    dimension_ffn: requis.dimension_ffn,
    nombre_tetes_attention: requis.nombre_tetes_attention,
    // GQA : moins de têtes KV que de têtes Q. Non déclaré = pas de GQA, les deux sont égales —
    // c'est la convention du format, pas une estimation de notre part.
    nombre_tetes_kv: gguf.attention.nb_tetes_kv ?? requis.nombre_tetes_attention,
    // Laissé à `null` quand absent : `budget.dimension_tete` sait dériver, et Qwen3 déclare un
    // `head_dim` qui NE suit PAS la convention embedding/têtes. Dériver ici serait faux.
    dimension_tete: gguf.attention.dimension_cle,
    contexte_entrainement_max: requis.contexte_entrainement_max,
    taille_vocabulaire: requis.taille_vocabulaire,
    quantification: gguf.quantification_mesuree ?? gguf.quantification_declaree,
    est_moe: (gguf.nb_experts ?? 0) > 1,
    // Sans ces champs, le planificateur ne peut PAS déporter les experts et coupe par couches
    // entières : sur un MoE, il fait alors payer au CPU toute l'attention d'une couche pour libérer
    // des experts dont 8 sur 256 sont lus par token. Ils étaient mesurés et envoyés ; seul
    // l'assemblage les perdait.
    nombre_experts: gguf.nb_experts,
    nombre_experts_actifs: gguf.nb_experts_actifs,
    dimension_ffn_expert: gguf.experts.largeur_ffn_expert,
    dimension_ffn_expert_partage: gguf.experts.largeur_ffn_partagee,
    intervalle_attention_pleine: gguf.attention.intervalle_attention_pleine,
    // Sans ces deux lignes, l'état récurrent reste chiffré à zéro côté planificateur — et le plan
    // promet une VRAM qu'il n'a pas. C'est le même oubli de transmission que les mesures par bloc.
    dimension_interne_ssm: gguf.ssm?.dimension_interne ?? null,
    dimension_etat_ssm: gguf.ssm?.dimension_etat ?? null,
    noyau_convolution_ssm: gguf.ssm?.noyau_convolution ?? null,
    ...mesuresParBloc(gguf, requis.nombre_couches),
  };
}

/*
 * Assemblage des métadonnées du planificateur à partir d'un `config.json` safetensors — symétrique
 * de `versMetadonneesPlan`. Le backend a déjà lu et MESURÉ (poids par bloc sur l'index des
 * tenseurs) ; ici on ne fait que confronter la présence des champs requis et transposer.
 */
export function versMetadonneesPlanSafetensors(
  modele: ModeleEnregistre,
  meta: MetadonneesSafetensors | null,
): MetadonneesModele | RefusCible {
  if (meta === null) {
    return {
      manquant: `métadonnées illisibles pour ${modele.id}`,
      remediation:
        modele.format === 'safetensors'
          ? REMEDIATION_METADONNEES
          : "Ce modèle n'est pas au format safetensors.",
    };
  }
  const estMoe = (meta.nb_experts ?? 0) > 1;
  const requis: Record<keyof ChampsRequis, number | RefusCible> = {
    nombre_couches: exiger(meta.nombre_couches, 'nombre de couches', 'le config.json'),
    dimension_embedding: exiger(meta.dimension_embedding, "dimension d'embedding", 'le config.json'),
    dimension_ffn: exiger(largeurFfnActiveSafetensors(meta, estMoe), 'dimension FFN', 'le config.json'),
    nombre_tetes_attention: exiger(meta.nombre_tetes_attention, "nombre de têtes d'attention", 'le config.json'),
    contexte_entrainement_max: exiger(meta.contexte_entrainement_max, "contexte d'entraînement", 'le config.json'),
    taille_vocabulaire: exiger(meta.taille_vocabulaire, 'taille du vocabulaire', 'le config.json'),
    taille_octets: exiger(meta.taille_octets, 'taille du fichier', 'le config.json'),
  };
  for (const valeur of Object.values(requis)) {
    if (estRefus(valeur)) {
      return valeur;
    }
  }
  return assemblerSafetensors(modele, meta, requis as ChampsRequis, estMoe);
}

/**
 * Largeur FFN vive d'un token. Dense : `dimension_ffn` (intermediate_size). MoE : experts routés
 * plus branche partagée, comme `MetadonneesGGUF.largeur_ffn_active` côté GGUF. `null` si un terme
 * manque — on ne complète pas une somme de moitié.
 */
function largeurFfnActiveSafetensors(meta: MetadonneesSafetensors, estMoe: boolean): number | null {
  if (!estMoe) {
    return meta.dimension_ffn;
  }
  if (meta.nb_experts_actifs === null || meta.dimension_ffn_expert === null) {
    return null;
  }
  return meta.nb_experts_actifs * meta.dimension_ffn_expert + (meta.dimension_ffn_expert_partage ?? 0);
}

function assemblerSafetensors(
  modele: ModeleEnregistre,
  meta: MetadonneesSafetensors,
  requis: ChampsRequis,
  estMoe: boolean,
): MetadonneesModele {
  return {
    identifiant: modele.id,
    format: modele.format,
    architecture: meta.architecture,
    taille_octets: requis.taille_octets,
    nombre_couches: requis.nombre_couches,
    dimension_embedding: requis.dimension_embedding,
    dimension_ffn: requis.dimension_ffn,
    nombre_tetes_attention: requis.nombre_tetes_attention,
    nombre_tetes_kv: meta.nombre_tetes_kv ?? requis.nombre_tetes_attention,
    dimension_tete: meta.dimension_tete,
    contexte_entrainement_max: requis.contexte_entrainement_max,
    taille_vocabulaire: requis.taille_vocabulaire,
    quantification: meta.quantification,
    est_moe: estMoe,
    nombre_experts: meta.nb_experts,
    nombre_experts_actifs: meta.nb_experts_actifs,
    dimension_ffn_expert: meta.dimension_ffn_expert,
    dimension_ffn_expert_partage: meta.dimension_ffn_expert_partage,
    intervalle_attention_pleine: meta.intervalle_attention_pleine,
    dimension_interne_ssm: meta.dimension_interne_ssm,
    dimension_etat_ssm: meta.dimension_etat_ssm,
    noyau_convolution_ssm: meta.noyau_convolution_ssm,
    ...mesuresParBlocSafetensors(meta, requis.nombre_couches),
  };
}

/*
 * Poids par bloc transmis seulement s'il est COMPLET (une valeur par couche) — sinon le
 * planificateur le refuse à juste titre et retombe sur le poids moyen. `octets_hors_blocs`
 * accompagne toujours une mesure par bloc : il porte la tour de vision et les embeddings, que le
 * chargement vLLM garde résidents en VRAM. Sans lui, ce poids serait perdu du calcul.
 */
function mesuresParBlocSafetensors(
  meta: MetadonneesSafetensors,
  nombreCouches: number,
): Pick<MetadonneesModele, 'octets_par_bloc' | 'octets_hors_blocs'> {
  if (meta.octets_par_bloc.length !== nombreCouches) {
    return {};
  }
  return {
    octets_par_bloc: meta.octets_par_bloc,
    octets_hors_blocs: meta.octets_hors_blocs,
  };
}

export function construireCible(
  modele: ModeleEnregistre,
  gguf: MetadonneesGGUF | null,
  profil: ProfilMachine,
  moteurs: EtatMoteurs | null,
  statut: StatutInference | null,
): ResultatCible {
  return assemblerCible(modele, versMetadonneesPlan(modele, gguf), profil, moteurs, statut);
}

export function construireCibleSafetensors(
  modele: ModeleEnregistre,
  meta: MetadonneesSafetensors | null,
  profil: ProfilMachine,
  moteurs: EtatMoteurs | null,
  statut: StatutInference | null,
): ResultatCible {
  return assemblerCible(modele, versMetadonneesPlanSafetensors(modele, meta), profil, moteurs, statut);
}

/** Assemble la cible finale une fois les métadonnées résolues — commun aux deux formats. */
function assemblerCible(
  modele: ModeleEnregistre,
  metadonnees: MetadonneesModele | RefusCible,
  profil: ProfilMachine,
  moteurs: EtatMoteurs | null,
  statut: StatutInference | null,
): ResultatCible {
  if ('manquant' in metadonnees) {
    return { refus: metadonnees };
  }
  const profilPlan = versProfilPlan(profil, moteurs, statut);
  if ('manquant' in profilPlan) {
    return { refus: profilPlan };
  }
  return {
    cible: {
      cheminModele: modele.chemin,
      nomModele: modele.fichier ?? modele.depot,
      // Préférences vides : l'utilisateur n'a rien demandé. Le planificateur décide seul, et c'est
      // exactement ce que l'écran de chat affichera comme plan initial.
      demande: { metadonnees, profil: profilPlan, preferences: {} },
    },
  };
}
