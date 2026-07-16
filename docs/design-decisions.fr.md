# Décisions de conception

🇬🇧 [English version](design-decisions.md)

> Le raisonnement derrière les choix qui façonnent ce projet. Chaque
> entrée énonce la décision, les alternatives considérées, et le
> pourquoi.

## 1. Le LLM ne choisit jamais un créneau

**Décision.** Les disponibilités et leur classement sont calculés par un
moteur déterministe. Le LLM n'interagit avec lui qu'à travers des outils
strictement validés et ne réserve que des `slot_id` retournés par le
moteur.

**Alternative considérée.** Donner au LLM le calendrier de la journée en
texte et le laisser raisonner sur les disponibilités.

**Pourquoi.** Les LLM excellent à comprendre « plutôt en fin de semaine,
mais pas vendredi » et sont peu fiables en arithmétique d'intervalles
sous pression. Une double réservation hallucinée est un échec
catastrophique pour un cabinet. Avec la frontière des outils, le pire
que le LLM puisse faire est de mal converser ; il ne peut pas corrompre
le calendrier. Cela rend aussi chaque réservation auditable : rejouez la
trace d'appels d'outils et vous pouvez prouver pourquoi un créneau a été
proposé.

## 2. Un score de compaction plutôt que « le premier créneau libre »

**Décision.** Les créneaux libres sont classés par adjacence aux
rendez-vous existants ; les créneaux isolés arrivent en dernier.

**Pourquoi.** Proposer le premier créneau libre déchiquette la journée
du praticien en trous de 15 minutes inutilisables. Une réceptionniste
expérimentée réserve contre les bords des rendez-vous existants pour
garder la journée compacte. Encoder cela comme une fonction de score
(plutôt que comme des instructions de prompt) rend le comportement
testable : une propriété Hypothesis affirme qu'aucun état de calendrier
aléatoire ne produit jamais de fragmentation évitable.

## 3. CalDAV comme unique source de vérité, pas de base de données parallèle

**Décision.** Le calendrier du cabinet (Radicale en développement,
iCloud ou Google en production) détient tout l'état des réservations.
Le moteur reçoit des intervalles occupés lus en direct depuis lui.

**Alternative considérée.** Refléter le calendrier dans une base locale
et synchroniser périodiquement.

**Pourquoi.** Un miroir invite à la dérive, et la dérive signifie des
doubles réservations. Plus important : les praticiens gèrent déjà leur
calendrier à la main et doivent garder ce pouvoir : bloquer un créneau,
déplacer un rendez-vous, fermer un après-midi, depuis leur propre
téléphone, sans nouvel outil à apprendre. CalDAV est un standard
ouvert : l'adaptateur écrit contre Radicale fonctionne contre n'importe
quel serveur de production, et le développement local ne coûte rien.

## 4. Relecture avant écriture à chaque réservation

**Décision.** Juste avant d'écrire un événement, l'adaptateur relit le
créneau visé. S'il n'est plus libre, la réservation est refusée et
l'agent propose autre chose.

**Pourquoi.** Le praticien peut prendre ou bloquer un créneau depuis son
téléphone pendant qu'un appelant est en ligne. Cette course est réelle
et inévitable ; le seul comportement correct est de la détecter au
moment de l'écriture et de récupérer conversationnellement (« ce
créneau vient d'être pris, je peux vous proposer 9h30 à la place »).

## 5. Des adaptateurs de fournisseurs partout

**Décision.** LLM, STT, TTS, téléphonie et calendrier sont chacun
derrière une petite interface avec au moins deux implémentations
prévues (une hébergée, une locale ou gratuite).

**Pourquoi.** Trois raisons. Aucune dépendance à un fournisseur pour
quiconque déploie le projet. Un chemin de développement à coût nul
(Radicale, Piper, paliers gratuits) qui garde le projet démontrable par
n'importe qui. Et une comparaison honnête : changer de fournisseur est
une variable d'environnement, donc les comparaisons ne coûtent rien.

## 6. Heure locale naïve à l'intérieur du moteur

**Décision.** Le moteur travaille en datetimes naïfs interprétés dans le
fuseau horaire du cabinet ; l'adaptateur calendrier détient toute la
conversion de fuseaux.

**Pourquoi.** Le planning d'un cabinet est local par nature (« nous
ouvrons à 08h00 »). Repousser la gestion des fuseaux à la frontière des
E/S garde le cœur pur simple et concentre les bugs d'heure d'été en un
seul endroit auditable.

## 7. La bascule de langue est marquée par le canal, pas devinée par le modèle

**Décision.** Chaque prise de parole de l'appelant porte un tag
`[lang=xx]` injecté par le harnais (issu de la détection de langue par
énoncé du STT sur les canaux vocaux). Le prompt système déclare le tag
contraignant pour la langue de la réponse.

**Alternative considérée.** Demander au modèle de détecter et suivre la
langue de l'appelant par lui-même.

**Pourquoi.** Les tests en conditions réelles ont été sans appel : avec
les seules instructions du prompt, gpt-4o-mini comme gemini-2.5-flash
continuaient de répondre en français après que l'appelant fut passé à
l'anglais, parce que l'historique de conversation pesait plus lourd que
l'instruction. Un tag déterministe venu de la couche de transcription a
tout réglé immédiatement. Même philosophie que la frontière de
planification : dès qu'un comportement doit être fiable, on le déplace
du prompt vers le harnais. La voix TTS est sélectionnée à partir du
même tag.

## 8. Les sessions réelles sont la suite de tests que le laboratoire ne peut pas écrire

**Décision.** Chaque session réelle sur le canal Telegram est analysée
depuis ses logs opérationnels et l'état brut du calendrier ; chaque
échec devient une protection dans le code, jamais un simple ajustement
de prompt.

**Ce que les premières sessions réelles ont appris, et ce que chaque
leçon est devenue :**

| Observé en réel | Protection livrée |
| --- | --- |
| Rendez-vous enregistré avec un nom de patient vide | book() valide le contenu de l'identité, pas seulement la présence dans le schéma |
| Réservations en double qui s'accumulent, appelant incapable de les voir ou de les annuler | L'outil find_bookings(phone) ferme la boucle vérifier/annuler/déplacer |
| 11 s de latence STT par clip | Clients HTTP persistants (mesuré de 3,0 s à 0,4 s) |
| Clips courts perdus ou détectés comme de l'allemand | Détection restreinte aux langues du cabinet |
| « Ce serait le mardi » entendu comme « Se croire le mardi » | Mode multilingue nova-3, langue dominante des mots |
| Un clip français transcrit en mandarin | Transcriptions non latines rejetées et retentées avec langue imposée |
| httpx.ReadTimeout avalait un tour en silence | Délais Telegram élargis + gestionnaire d'erreurs qui répond toujours |

Les sessions temps réel (console) ont ajouté leurs propres lignes :

| Observé en réel | Protection livrée |
| --- | --- |
| Tours transcrits mais jamais répondus | LLM factice au niveau session (livekit saute la génération quand llm vaut None, même avec llm_node surchargé) |
| 12,7 s de délai de transcription | Micro du casque Bluetooth identifié ; un micro filaire a ramené cela à environ 0,5 s |
| 5-13 s de silence pendant les tours d'outils | Tours du cerveau pilotés par événements + phrase d'attente parlée (« un instant, je consulte le planning ») |
| Un tour français transcrit en japonais a atteint le cerveau | Garde mostly_latin partagée entre canaux ; le temps réel demande de répéter |
| Identité déformée (« Bon nom complique ben jao ») réservée telle quelle | Faire épeler les noms, téléphones chiffre par chiffre, relecture obligatoire ; la boucle de correction des chiffres a fonctionné dès la session suivante |

Puis le harnais d'évaluation (phase 5) a industrialisé la boucle et
ajouté :

| Attrapé par une campagne | Protection livrée |
| --- | --- |
| L'appelant a donné un numéro au format local (« 94 22 11 00 ») ; la recherche en égalité stricte a manqué la réservation et un doublon a été créé | phones_match par suffixe partagé dans tout l'adaptateur, couvert par un test de régression |
| Aucun jour donné par l'appelant : l'agent a réservé AUJOURD'HUI en silence | Prompt : demander le jour, ne jamais supposer |
| L'agent a conseillé à un appelant de « contacter le cabinet » (il EST le cabinet) | Prompt : vous êtes la réception, proposez ce que vous savez faire |
| Des checks plus stricts que l'architecture (classement refusé par une garde signalé comme violation ; horaires répétés depuis les mots de l'appelant signalés) | Checks calibrés : les refus sont la garde qui fonctionne ; répéter l'appelant, c'est de la conversation |

**Pourquoi c'est important.** L'audio synthétique (clips de test générés
par TTS) passe là où les vrais micros de téléphone échouent.
L'aller-retour de laboratoire a validé le pipeline ; seules les sessions
de production ont fait émerger ces sept échecs. Le harnais d'évaluation
(phase 5) en automatise une partie, mais le principe demeure : juger le
système sur ses logs et son état persisté, pas sur ses réponses.

## 9. Le canal temps réel emprunte le corps de LiveKit, jamais son cerveau

**Décision.** Le canal LiveKit surcharge `Agent.llm_node` pour que le
BookingAgent du projet produise chaque réponse ; LiveKit ne fournit que
le micro, le VAD, le STT en streaming, l'interruption et la lecture TTS.

**Alternative considérée.** Utiliser la boucle d'agent propre à LiveKit
avec son plugin LLM et réenregistrer les outils de réservation comme
function tools LiveKit.

**Pourquoi.** Cela signifierait deux cerveaux : deux registres d'outils,
deux jeux de prompts, deux comportements à tester et qui divergeraient.
Avec la surcharge, il y a un seul cerveau partagé par la CLI, Telegram
et le temps réel, et tout ce que la suite de tests prouve à son sujet
vaut sur chaque canal. Le coût accepté : la réponse atteint le TTS en un
seul bloc au lieu d'un streaming token par token (environ une seconde de
latence), compensé par la phrase d'attente parlée pendant les tours
d'outils.

## 10. Modèles figés, typage strict, tests par propriétés

**Décision.** Tous les modèles du domaine sont des modèles pydantic
immuables ; mypy tourne en mode strict ; les invariants sont testés avec
Hypothesis, pas seulement par exemples.

**Pourquoi.** Le moteur est l'ancre de confiance de tout le système.
L'immuabilité élimine une classe de bugs d'aliasing, le typage strict
attrape les dérives d'interface à l'arrivée de l'agent et des
adaptateurs, et les tests par propriétés énoncent les vraies garanties
(« les créneaux proposés sont toujours libres », « aucune fragmentation
évitable ») au lieu de les échantillonner.
