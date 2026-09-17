-- Teste l'encodeur JSON de wingbridge.lua HORS de MA3.
--
-- Pourquoi : ExportJson de MA3 produit du JSON invalide (clés sans
-- guillemets, vérifié), on écrit donc le nôtre. Un encodeur
-- maison doit être testé, sinon on remplace un format cassé par un autre.
--
-- Le code testé est EXTRAIT du plugin réel, pas recopié : si le plugin change,
-- ce test suit. Sortie sur stdout, validée ensuite par Python.

local src = io.open("wingbridge.lua"):read("a")
local debut = src:find("local function echapper")
local fin = src:find("local function chemin")
assert(debut and fin, "bloc encodeur introuvable dans wingbridge.lua")
local bloc = src:sub(debut, fin - 1)

local charger = load(bloc .. "\nreturn encoder")
assert(charger, "le bloc encodeur ne compile pas")
local encoder = charger()

-- Cas représentatif : exactement la forme produite par la sonde.
-- ⚠️ `horodate` et `tours` sont des ENTIERS epoch/compteur : un encodeur qui
-- passe par `%.6g` les écrase (1787944439 -> 1.78794e+09). Valeurs choisies
-- assez grandes pour piéger ça (bug diagnostiqué).
local echantillon = {
    version = 2,
    horodate = 1787944439,
    tours = 1234567,
    erreurs = 0,
    duree_ms = 7,
    page = { index = 2, no = 2, nom = 'Page "2"', addr = "Page 2" },
    executors = {
        { no = 201, nom = "Spots", fader = 87.5, libelle = "Master",
          tourne = true, active = true },
        { no = 202, nom = nil, fader = 0, libelle = "", tourne = false },
    },
}
print(encoder(echantillon))
