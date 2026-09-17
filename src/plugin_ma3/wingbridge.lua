-- ===========================================================================
--  Wing Bridge - sonde d'etat grandMA3
--  Version 3 : page courante + executors + etat des sequences.
--  Versions grandMA3 testees : 2.4.x et 2.5.x (jusqu'a 2.5.0.3, Lua 5.5).
-- ===========================================================================
--
--  POURQUOI CE PLUGIN EXISTE
--  L'OSC est unidirectionnel dans ce projet : MA3 n'annonce ni sa page
--  courante, ni l'etat de ses sequences, ni la position reelle de ses faders.
--  Quatre fonctions de Wing Bridge etaient bloquees la-dessus :
--    - LED des executors refletant l'etat reel de MA3
--    - conscience de la page executor courante
--    - rattrapage de fader (retire une premiere fois, faute de cette information)
--    - avertissement quand le type de fader choisi ne correspond pas a MA3
--  Cette sonde les debloque toutes les quatre.
--
--  COMMENT L'INFO SORT DE MA3
--  Lua n'a pas de sockets (bibliotheques standard uniquement ; luasocket n'en
--  fait pas partie). On passe par un FICHIER que Wing Bridge relit.
--  Acceptable ICI ET SEULEMENT ICI : la cible du projet est grandMA3 onPC,
--  qui tourne forcement sur la meme machine que Wing Bridge.
--
--  ===========================================================================
--  CE QUI A ETE ETABLI PAR L'EXPERIENCE - ne pas re-supposer
--  ===========================================================================
--
--  ACCES AUX EXECUTORS
--    page:Children() parcouru avec pairs()   <- LA SEULE voie qui marche
--    GetExecutor(n)              -> nil, quel que soit n
--    GetObject("Page 2.201")     -> nil
--    ObjectList("Page 2.*")      -> 0
--    page:Ptr(i)                 -> nil, quel que soit i
--    !! page:Count() est la CAPACITE de la page (390), PAS le nombre
--       d'executors. Contresens qui a fait boucler la sonde dans le vide.
--    !! ne jamais compter Children() avec # : la table peut rendre 0 alors
--       qu'elle est pleine. pairs(), toujours.
--
--  LECTURES QUI FONCTIONNENT
--    ex:GetFader({})       -> number 0..100      position reelle
--    ex:GetFaderText({})   -> string "42%"
--    ex.no / ex.name       -> numero / nom de l'objet assigne
--    ex.fader              -> "Master", "X", "Temp"...  FONCTION du fader
--    ex.key                -> "Go+", "Flash"...        fonction de la touche
--    ex.faderenabled       -> boolean
--    ex.object             -> POIGNEE de la sequence assignee
--
--  ETAT DE LECTURE : sur la SEQUENCE, jamais sur l'executor
--    ex:IsRunningPlayback()      -> nil          (piege)
--    ex.object:IsRunningPlayback() -> boolean    OK
--    ex.object:HasActivePlayback() -> boolean    OK
--
--  !! ON N'UTILISE PAS ExportJson() : sa doc previent que la sortie peut ne
--  pas etre du JSON valide. Verifie - les cles sortent sans guillemets. On
--  ecrit le JSON a la main. Ne pas "simplifier" en revenant a ExportJson.
--
--  !! ECRITURE ATOMIQUE : .tmp puis os.rename. Wing Bridge relit ce fichier
--  en permanence et ne doit jamais tomber sur une moitie de fichier.
--
--  !! LA DOC DE MA3 EST FAUSSE SUR CE POINT. Elle affirme que Timer() prend
--  un delai en SECONDES ENTIERES (page lua_objectfree_timer). Mesure : les
--  fractions marchent parfaitement. Cadence reelle relevee sur les dates du
--  fichier avec PERIODE_S = 0.2 :
--      0.194  0.198  0.198  0.212  0.194  0.194  0.203  0.199  -> 0.20 s
--  Cout mesure : 0 a 7 ms par releve, soit 3,5 % d'un coeur au pire.
--  Augmenter PERIODE_S si la console peine ; 1.0 reste tres confortable.
--
--  ===========================================================================
--  INSTALLATION - PAR L'AMORCE, c'est la seule a retenir
--    1. Sur le Mac : ./installer.sh
--    2. Dans MA3 :   Import Plugin Library "wingloader.xml" At 3
--                    Set Plugin 3.1 Property "Installed" "Yes"
--                    Plugin 3        (bascule marche/arret de la sonde)
--    3. ENREGISTRER LE SHOW (l'emplacement du plugin en fait partie)
--
--  MISE A JOUR : ./installer.sh, puis "Plugin 3" deux fois (arret/marche).
--  L'amorce relit CE fichier a chaque appel : ni ReloadAllPlugins, ni
--  re-import, ni redemarrage de MA3. Voir wingloader.lua.
--
--  !! On n'importe PAS wingbridge.xml directement. C'etait la methode d'avant
--  l'amorce : MA3 garde alors en memoire le code Lua deja charge, et aucune
--  des trois voies habituelles ne le remplace. Chaque
--  correction demandait un redemarrage complet de la console. wingbridge.xml
--  reste livre pour ce cas de secours, rien de plus.
-- ===========================================================================

local NOM_FICHIER = "wingbridge_state.json"
local PERIODE_S   = 0.2
local PAR_SALVE   = 300
-- PIEGES DU CHAMP `horodate`, tous les deux payes :
--   - `Time()` ne renvoie PAS un epoch (mesure Windows : 17931 = uptime) ;
--     `os.time()` si.
--   - meme avec la bonne source, l'ENCODEUR JSON (`encoder`, plus bas) ecrasait
--     tout entier >= 7 chiffres via `%.6g`. Les entiers sortent en `%d`.
-- Champs retires apres confirmation par observation en MA3 reel (voir
-- docs/GRANDMA3_SYNC.md) : `feature_enfants`/`feature_enfants_note`
-- (`SelectedFeature():Children()` : toujours {} vide, piste tranchee negative),
-- `fixture_index` (jamais lu), `canaux[].feature` (valait toujours "UIChannels",
-- l'app calcule le feature reel depuis le XML), `interface` de lire_osc (jamais
-- expose par osc_config_ma3), `executor`/`special` de lire_raccourci (non lus).
-- Le bump de VERSION sert a verifier dans /api/status / le fichier d'etat que
-- la sonde redeployee est bien la nouvelle.
local VERSION     = 13

-- Les raccourcis clavier changent rarement : les relire 5 fois par seconde
-- serait du gaspillage pur. Une fois toutes les 3 s suffit largement.
local RACCOURCIS_PERIODE_S = 3.0

-- L'etat est global : il SURVIT a ReloadAllPlugins, contrairement au code.
-- Sans `generation`, chaque demarrage ajoutait une chaine de Timer sans tuer
-- les precedentes (compteur monte a 3230 releves apres deux "arrets").
local etat = _G.WingBridgeEtat
      or { actif = false, tours = 0, erreurs = 0, generation = 0 }
etat.generation = etat.generation or 0
_G.WingBridgeEtat = etat

local armer


-- -- Encodage JSON -------------------------------------------------------------

local function echapper(s)
    s = tostring(s)
    s = s:gsub("\\", "\\\\"):gsub('"', '\\"')
    s = s:gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t")
    return s
end

local function encoder(v)
    local t = type(v)
    if v == nil then
        return "null"
    elseif t == "boolean" then
        return v and "true" or "false"
    elseif t == "number" then
        if v ~= v or v == math.huge or v == -math.huge then return "null" end
        -- ⚠️ `%.6g` casse tout entier de 7 chiffres ou plus en scientifique
        -- tronquee a 6 sig. figs : 1787944439 (epoch os.time) devient
        -- « 1.78794e+09 » = 1787940000 a la relecture, ~4000 s de perte.
        -- Touche aussi `tours` des qu'il depasse 999999 (~2,5 j de marche).
        -- Diagnostic confirme (Mac + Windows). Donc : les
        -- valeurs ENTIERES sortent en `%d` (exactes), seules les vraies
        -- fractions gardent `%.6g` (position de fader, latences...).
        if v == math.floor(v) and math.abs(v) < 1e15 then
            return string.format("%d", v)
        end
        return string.format("%.6g", v)
    elseif t == "table" then
        if #v > 0 then
            local m = {}
            for i = 1, #v do m[#m + 1] = encoder(v[i]) end
            return "[" .. table.concat(m, ",") .. "]"
        end
        local m = {}
        for cle, val in pairs(v) do
            m[#m + 1] = '"' .. echapper(cle) .. '":' .. encoder(val)
        end
        return "{" .. table.concat(m, ",") .. "}"
    end
    return '"' .. echapper(v) .. '"'
end


local function chemin()
    local base = GetPath(Enums.PathType.Library)
    local sep = "/"
    if GetPathSeparator then sep = GetPathSeparator() end
    return base .. sep .. NOM_FICHIER
end


-- Pause active courte (MA3 Lua n'expose pas de sleep). UNIQUEMENT sur le chemin
-- d'echec du rename (rare), pour laisser un lecteur relacher le fichier avant de
-- retenter. Filet `garde` : ne jamais boucler indefiniment si os.clock stagne.
local function pause_ms(ms)
    local fin = (os.clock and os.clock() or 0) + ms / 1000.0
    local garde = 0
    while (os.clock and os.clock() or 0) < fin do
        garde = garde + 1
        if garde > 50000000 then break end
    end
end


local function ecrire(texte)
    local cible = chemin()
    local tmp = cible .. ".tmp"
    local f, err = io.open(tmp, "w")
    if not f then return false, "io.open : " .. tostring(err) end
    f:write(texte)
    f:close()
    -- Ecriture atomique : .tmp puis rename. POSIX ECRASE la cible ; Windows
    -- REFUSE os.rename si la cible existe deja ("File exists", errno EEXIST) —
    -- on l'efface alors d'abord puis on renomme.
    --
    -- 🪟 MAIS sous Windows, si un LECTEUR (l'app, Defender) tient la
    -- cible ouverte AU MEME INSTANT, `remove` ET `rename` echouent (violation de
    -- partage) : l'ecriture du tick est perdue. Echec TRANSITOIRE, prouve par
    -- test causal (une lecture intensive triple le taux, .tmp residuel) : ~1,5 %
    -- des ecritures a 20 lect./s. On RETENTE avec un court back-off — le lecteur
    -- relache vite (une lecture coute ~0,5 ms), un ou deux essais suffisent.
    -- POSIX n'est pas concerne : son premier rename reussit, la boucle s'arrete
    -- au 1er tour.
    local ESSAIS = 4
    local err2
    for i = 1, ESSAIS do
        local ok = os.rename(tmp, cible)
        if ok then return true end
        os.remove(cible)                 -- peut echouer si un lecteur tient la cible
        ok, err2 = os.rename(tmp, cible)
        if ok then return true end
        if i < ESSAIS then pause_ms(2 * i) end   -- back-off 2, 4, 6 ms, borne
    end
    return false, "os.rename apres " .. ESSAIS .. " essais : " .. tostring(err2)
end


-- -- Lectures MA3 -------------------------------------------------------------

-- Chaque acces est protege : selon les versions de MA3, tel champ peut
-- manquer. Un champ absent doit couter nil, pas l'arret de la sonde. Mais rien
-- ne doit echouer EN SILENCE : tout est compte dans `erreurs`.
local function essai(fn)
    local ok, v = pcall(fn)
    if ok then return v end
    etat.erreurs = etat.erreurs + 1
    return nil
end


local function lire_page()
    local h = CurrentExecPage()
    if not h then return nil end
    return {
        no   = essai(function() return h.no end),
        nom  = essai(function() return h.name end),
        addr = essai(function() return ToAddr(h, false) end),
    }
end


local function lire_executor(ex)
    local e = {
        no       = essai(function() return ex.no end),
        nom      = essai(function() return ex.name end),
        fader    = essai(function() return ex:GetFader({}) end),
        texte    = essai(function() return ex:GetFaderText({}) end),
        -- fonction reglee DANS MA3 : "Master", "X", "Temp", "Rate"...
        -- C'est elle qui permet d'avertir quand elle ne correspond pas au
        -- type choisi dans Wing Bridge, sans jamais ecrire dans le showfile.
        fonction = essai(function() return ex.fader end),
        touche   = essai(function() return ex.key end),
        actif    = essai(function() return ex.faderenabled end),
    }

    -- L'etat de lecture se lit sur la SEQUENCE, pas sur l'executor.
    local obj = essai(function() return ex.object end)
    if type(obj) == "userdata" then
        e.objet  = essai(function() return obj.name end)
        e.classe = essai(function() return obj:GetClass() end)
        e.tourne = essai(function() return obj:IsRunningPlayback() end)
        e.active = essai(function() return obj:HasActivePlayback() end)
        e.cue    = essai(function() return obj.cuename end)
    end
    return e
end


local function lire_executors()
    local page = CurrentExecPage()
    if not page then return {} end
    local enfants = essai(function() return page:Children() end)
    if type(enfants) ~= "table" then return {} end
    local liste = {}
    for _, ex in pairs(enfants) do       -- pairs, JAMAIS ipairs ni #
        liste[#liste + 1] = lire_executor(ex)
    end
    return liste
end


-- -- Masters (GrandMaster, Speed Masters, masters de selection) --------------
--
-- Etabli par sonde reelle (voir docs/GRANDMA3_SYNC.md) :
-- MasterPool() rend un handle avec exactement 5 enfants, chacun un POOL
-- (pas un master individuel) : no=1 Selected, no=2 Grand, no=3 Speed,
-- no=4 Playback, no=5 Timing. Seuls Selected/Grand/Speed nous interessent ici
-- (Playback/Timing n'ont pas d'equivalent cote profil Wing Bridge).
--
-- Chaque POOL a lui-meme des enfants qui sont les masters INDIVIDUELS,
-- adressables par leur `.no` (1-based) - c'est EXACTEMENT la numerotation de
-- la syntaxe MA3 (`Master 2.1` = pool Grand, enfant no=1 ; `Master 3.7` = pool
-- Speed, enfant no=7 ; `Master 1.2` = pool Selected, enfant no=2 = XFade).
-- `h:GetFader({})` sur un enfant individuel rend directement sa valeur
-- 0..100 - MEME MECANISME que `ex:GetFader({})` sur un executor, aucune
-- logique parallele.
local function lire_pool_masters(pool_handle)
    local enfants = essai(function() return pool_handle:Children() end)
    if type(enfants) ~= "table" then return {} end
    local t = {}
    for _, h in pairs(enfants) do
        local no = essai(function() return h.no end)
        local fader = essai(function() return h:GetFader({}) end)
        if type(no) == "number" and type(fader) == "number" then
            t[tostring(no)] = fader
        end
    end
    return t
end

local function lire_masters()
    local mp = essai(function() return MasterPool() end)
    if type(mp) ~= "userdata" then return nil end
    local pools = essai(function() return mp:Children() end)
    if type(pools) ~= "table" then return nil end
    local resultat = { selected = {}, grand = {}, speed = {} }
    for _, p in pairs(pools) do
        local no = essai(function() return p.no end)
        if no == 1 then resultat.selected = lire_pool_masters(p)
        elseif no == 2 then resultat.grand = lire_pool_masters(p)
        elseif no == 3 then resultat.speed = lire_pool_masters(p)
        end
    end
    return resultat
end


-- -- Raccourcis clavier : la table REELLE de MA3 -----------------------------
--
--  POURQUOI. Wing Bridge ecrit les raccourcis de MA3 dans
--  WingBridge.xml puis envoie "Set KeyboardShortcut <n> Property ...". Mais
--  l'OSC n'accuse JAMAIS reception : l'app relisait donc SON PROPRE fichier
--  pour annoncer "c'est bon". MA3 ferme, OSC coupe, port faux : elle affichait
--  le meme succes. Troisieme fois que ce projet se fait avoir par un message
--  de reussite qu'on n'a pas verifie.
--
--  Cette sonde tourne DANS MA3 : elle seule peut dire ce que la console a
--  VRAIMENT. C'est la seule confirmation honnete possible.
--
--  ⚠️ LE CHEMIN D'ACCES N'EST PAS CONNU. Plutot que de le deviner - ce qui a
--  deja coute cher ici - on essaie plusieurs voies et on ECRIT LAQUELLE A
--  MARCHE (champ "via"). Quand une aura fait ses preuves, on pourra tailler.
--  Tant qu'aucune ne marche, "via" vaut nil et l'app le dit franchement au
--  lieu de faire semblant.

local RAC = { t = 0, liste = nil, via = nil, note = nil }


-- Voies candidates. Chacune doit rendre une COLLECTION parcourable, ou nil.
local function voies_raccourcis()
    return {
        { nom = "ObjectList('KeyboardShortcut')", fn = function()
            return ObjectList("KeyboardShortcut") end },
        { nom = "ObjectList('KeyboardShortcut 1 Thru')", fn = function()
            return ObjectList("KeyboardShortcut 1 Thru") end },
        { nom = "GetObject('KeyboardShortcut')", fn = function()
            return GetObject("KeyboardShortcut"):Children() end },
        { nom = "Root().UserProfiles...KeyboardShortCuts", fn = function()
            -- On descend en cherchant un enfant dont le nom evoque les
            -- raccourcis : la casse et le pluriel varient selon les versions.
            local function chercher(obj, profondeur)
                if profondeur > 3 or type(obj) ~= "userdata" then return nil end
                local enfants = obj:Children()
                if type(enfants) ~= "table" then return nil end
                for _, e in pairs(enfants) do
                    local n = tostring(e.name or ""):lower()
                    if n:find("keyboardshortcut") or n:find("shortcut") then
                        return e:Children()
                    end
                    local trouve = chercher(e, profondeur + 1)
                    if trouve then return trouve end
                end
                return nil
            end
            return chercher(Root(), 0)
        end },
    }
end


-- Lecture d'UN raccourci. Les noms de proprietes ne sont pas documentes cote
-- Lua : on essaie les formes plausibles et on garde ce qui repond.
local function lire_raccourci(o, rang)
    local function champ(...)
        for _, nom in ipairs({ ... }) do
            local v = essai(function() return o[nom] end)
            if v ~= nil and v ~= "" then return v end
        end
        return nil
    end
    -- `keycode` sert de garde interne cote app (liste[1].keycode ~= nil, cf.
    -- wing_raccourcis.py) ; `frappe` est le seul champ reellement lu. Les
    -- champs `executor`/`special` ont ete retires (sonde v13) : jamais lus.
    return {
        no      = rang,
        keycode = champ("keycode", "KeyCode", "key"),
        frappe  = champ("shortcut", "Shortcut"),
    }
end


local function lire_raccourcis()
    -- Cadence propre : cette lecture est bien plus lourde que les executors.
    local maintenant = os.time and os.time() or 0
    if RAC.liste and (maintenant - RAC.t) < RACCOURCIS_PERIODE_S then
        return RAC.liste, RAC.via, RAC.note
    end
    RAC.t = maintenant

    for _, voie in ipairs(voies_raccourcis()) do
        local ok, col = pcall(voie.fn)
        if ok and type(col) == "table" then
            local liste, rang = {}, 0
            for _, o in pairs(col) do            -- pairs, JAMAIS ipairs (cf. en-tete)
                rang = rang + 1
                liste[#liste + 1] = lire_raccourci(o, rang)
            end
            -- Une collection vide ne prouve rien : on continue de chercher.
            if #liste > 0 and liste[1].keycode ~= nil then
                RAC.liste, RAC.via, RAC.note = liste, voie.nom, nil
                return RAC.liste, RAC.via, RAC.note
            end
            if #liste > 0 then
                -- On a bien une collection, mais aucun nom de propriete n'a
                -- repondu. C'est une information utile : on la remonte.
                RAC.note = voie.nom .. " : " .. #liste ..
                           " objets, mais aucune propriete lisible"
            end
        end
    end
    RAC.liste, RAC.via = nil, nil
    RAC.note = RAC.note or "aucune voie d'acces n'a fonctionne"
    return nil, nil, RAC.note
end


-- -- Encoder Bar : les attributs REELS du projecteur selectionne ------------
--
--  OBJECTIF : que les 4 roues de la wing fassent ce que l'Encoder Bar
--  affiche, comme sur une vraie console.
--
--  ⚠️⚠️ CORRECTION DE FOND (v5 -> v6).
--  La v5 lisait GetAttributeByUIChannel(0..N) SANS projecteur : elle rendait
--  la liste GLOBALE de tous les attributs possibles (1218 canaux, Dimmer aux
--  index 0 ET 8...). Or CHAQUE projecteur a SES attributs : un spot RVB, un
--  CMJ et une lyre a roue de couleur n'ont pas les memes. Comparer a une table
--  globale ne pouvait pas marcher - c'etait approximatif, donc faux.
--
--  LA BONNE VOIE, telle que le manuel la documente noir sur blanc :
--    SelectionFirst()              -> patch index du 1er projecteur choisi
--    GetSubfixture(index)          -> son handle
--    GetUIChannels(handle, true)   -> les canaux de CE projecteur (RVB != CMJ)
--    <canal>.name / feature        -> vrai nom d'attribut et son feature
--  « Attributes are what is controlled using the Encoder bar » (manuel).
--
--  ⚠️ NE PAS CONFONDRE avec /EncoderX de l'OSC : celui-la vise les
--  MINI-ENCODEURS D'EXECUTOR (« /Encoder201 »). Piege de la tache #24.
--
--  ON PUBLIE ENCORE LE RELEVE BRUT, pas une conclusion : la sonde donne, pour
--  le 1er projecteur selectionne, la liste ordonnee de ses attributs avec leur
--  feature. C'est l'app qui, avec le feature selectionne, decidera quels
--  attributs sont sous les roues - et l'AFFICHERA pour qu'un ecart se voie.
--  Tant qu'on n'a pas observe sur une vraie selection heterogene (RVB + CMJ),
--  on ne suppose rien sur ce que MA3 fait d'une selection mixte.

local ENC = { t = 0, data = nil }
local ENCODEURS_PERIODE_S = 0.5
local ENC_MAX = 64          -- garde-fou : un projecteur n'a pas 500 attributs


local function nom_handle(h)
    if type(h) ~= "userdata" then return nil end
    return essai(function() return h.name end)
end


local function lire_encodeurs()
    local maintenant = os.time and os.time() or 0
    if ENC.data and (maintenant - ENC.t) < ENCODEURS_PERIODE_S then
        return ENC.data
    end
    ENC.t = maintenant

    local d = {}
    d.selection = essai(function() return SelectionCount() end)
    d.attribut  = nom_handle(essai(function() return GetSelectedAttribute() end))

    d.feature = nom_handle(essai(function() return SelectedFeature() end))

    -- Piste "SelectedFeature():Children() enumere-t-il les attributs de la
    -- Feature active, dans le bon ordre ?" : TRANCHEE NEGATIVE a l'audit - la
    -- table etait toujours vide, meme fixture selectionnee + Feature active.
    -- L'ordre reel de l'Encoder Bar se
    -- reconstruit cote app depuis attribute_definitions.xml (_feature_par_attribut).
    -- Le releve `feature_enfants` a donc ete retire (sonde v13).

    -- 1er projecteur selectionne. SelectionFirst rend plusieurs entiers ; le
    -- premier est le patch index (0-based). nil = rien de selectionne.
    local idx = essai(function() return (SelectionFirst()) end)
    if idx == nil then
        d.note = "aucune fixture selectionnee"
        d.canaux = {}
        ENC.data = d
        return d
    end

    local fix = essai(function() return GetSubfixture(idx) end)
    d.fixture = nom_handle(fix)
    if type(fix) ~= "userdata" then
        d.note = "GetSubfixture(" .. tostring(idx) .. ") n'a pas rendu de handle"
        d.canaux = {}
        ENC.data = d
        return d
    end

    -- Canaux UI de CE projecteur, en HANDLES (2e argument = true).
    local uic = essai(function() return GetUIChannels(fix, true) end)
    local canaux = {}
    if type(uic) == "table" then
        -- pairs, jamais ipairs : coherent avec le reste de la sonde.
        for _, h in pairs(uic) do
            if #canaux >= ENC_MAX then break end
            local nom = nom_handle(h)
            if nom then
                -- OBSERVATION SEULE (etape 0) - AVANT tout pilotage.
                -- L'exemple OFFICIEL de GetUIChannels dans le manuel installe
                -- (lua_objectfree_getuichannels.html) lit value.SUBATTRIBUTE
                -- et value.INDEX, JAMAIS .name. Or FADERS_ENCODERS.md decrit
                -- deja un piege identique (bug "Focus") : le
                -- libelle affiche par l'Encoder Bar n'est PAS forcement le
                -- vrai mot-cle d'attribut (Focus affiche pour l'attribut reel
                -- Focus1). On remonte donc les TROIS champs, en observation
                -- seule - AUCUNE commande OSC ne part d'ici - pour trancher
                -- lequel est fiable avant de cabler un pilotage dessus.
                local subattr   = essai(function() return h.SUBATTRIBUTE end)
                local canal_idx = essai(function() return h.INDEX end)
                canaux[#canaux + 1] = { nom = nom,
                                         subattribut = subattr, index = canal_idx }
            end
        end
    else
        d.note = "GetUIChannels n'a pas rendu de table"
    end
    d.canaux = canaux
    ENC.data = d
    return d
end


-- -- Configuration OSC de MA3 : le port et l'etat d'entree, EN VRAI ---------
--
--  POURQUOI. L'app detecte tres bien que MA3 n'ecoute pas l'OSC
--  (aucun socket sur le port vise), mais elle ne sait pas POURQUOI, et son
--  message accusait une machine virtuelle... alors qu'aucune ne tournait.
--  Un diagnostic juste double d'une explication fausse.
--
--  Releve : MA3 tournait (pid 3101), zero socket UDP sur 8000,
--  aucune VM. Donc l'entree OSC etait bel et bien inactive - reste a savoir
--  si elle est desactivee, ou reglee sur un autre port.
--
--  La sonde tourne DANS MA3 : elle peut lire la configuration elle-meme.
--  Le manuel situe l'objet en ShowData/OSCBase (mot-cle OSC :
--  "ChangeDestination OSC" -> User@ShowData/OSCBase). Le chemin Lua exact
--  n'est pas documente : on essaie plusieurs voies et on ecrit LAQUELLE a
--  marche, comme pour les raccourcis.

local OSCCFG = { t = 0, data = nil }
local OSC_PERIODE_S = 2.0


local function voies_osc()
    return {
        { nom = "ShowData().OSCBase", fn = function()
            return ShowData().OSCBase end },
        { nom = "Root().ShowData.OSCBase", fn = function()
            return Root().ShowData.OSCBase end },
        { nom = "ShowData() -> enfant nomme OSC", fn = function()
            local enfants = ShowData():Children()
            if type(enfants) ~= "table" then return nil end
            for _, e in pairs(enfants) do
                local n = tostring(e.name or ""):lower()
                if n:find("osc") then return e end
            end
            return nil
        end },
    }
end


local function lire_osc()
    local maintenant = os.time and os.time() or 0
    if OSCCFG.data and (maintenant - OSCCFG.t) < OSC_PERIODE_S then
        return OSCCFG.data
    end
    OSCCFG.t = maintenant

    local d = {}
    for _, voie in ipairs(voies_osc()) do
        local ok, base = pcall(voie.fn)
        if ok and type(base) == "userdata" then
            d.via = voie.nom
            -- Reglages du MENU (haut de la fenetre OSC).
            d.entree = essai(function() return base.enableinput end)
            d.sortie = essai(function() return base.enableoutput end)
            -- Chaque configuration OSC est un enfant : nom, port, mode...
            local confs = {}
            local enfants = essai(function() return base:Children() end)
            if type(enfants) == "table" then
                for _, c in pairs(enfants) do
                    confs[#confs + 1] = {
                        nom     = essai(function() return c.name end),
                        port    = essai(function() return c.port end),
                        recoit  = essai(function() return c.receive end),
                        envoie  = essai(function() return c.send end),
                        -- « Receive Command » : c'est CE reglage qui autorise
                        -- la ligne de commande - donc tout Wing Bridge.
                        rec_cmd = essai(function() return c.receivecommand end),
                        env_cmd = essai(function() return c.sendcommand end),
                        dest    = essai(function() return c.destinationip end),
                    }
                end
            end
            d.configs = confs
            OSCCFG.data = d
            return d
        end
    end
    d.note = "aucune voie d'acces a la configuration OSC n'a fonctionne"
    OSCCFG.data = d
    return d
end


-- -- Boucle -------------------------------------------------------------------

local function releve(gen)
    if not etat.actif or gen ~= etat.generation then return end
    etat.tours = etat.tours + 1
    local t0 = os.clock and os.clock() or 0

    local ok, donnees = pcall(function()
        local d = {
            version   = VERSION,
            -- `os.time()` = epoch Unix en secondes, comme ailleurs dans ce
            -- fichier. PAS `Time()` : mesure sur le fichier
            -- d'etat reel, `Time()` renvoie l'epoch ARRONDI par paquets de
            -- 10000 s (~2 h 47) -> un script calculant « age = maintenant -
            -- horodate » lisait jusqu'a 10000 s de silence sur une sonde
            -- pourtant vivante (faux « sonde morte »). Repli `Time()` si
            -- `os.time` absent, comme le reste du fichier.
            horodate  = (os.time and os.time()) or Time(),
            tours     = etat.tours,
            page      = lire_page(),
            executors = lire_executors(),
        }
        -- ⚠️ Isole dans son propre pcall : une nouveaute qui echoue ne doit
        -- PAS emporter le releve des executors, qui marche de longue date.
        local ok2, liste, via, note = pcall(lire_raccourcis)
        if ok2 then
            d.raccourcis      = liste
            d.raccourcis_via  = via
            d.raccourcis_note = note
        else
            d.raccourcis_note = "lecture impossible : " .. tostring(liste)
        end
        -- Meme isolement : l'Encoder Bar est une nouveaute, elle ne doit pas
        -- pouvoir emporter le releve des executors.
        local ok3, enc = pcall(lire_encodeurs)
        d.encodeurs = ok3 and enc or nil
        if not ok3 then
            d.encodeurs_note = "lecture impossible : " .. tostring(enc)
        end
        -- Isole aussi : une nouveaute ne doit jamais emporter le reste.
        local ok4, oscc = pcall(lire_osc)
        d.osc = ok4 and oscc or nil
        if not ok4 then
            d.osc_note = "lecture impossible : " .. tostring(oscc)
        end
        -- Isole pareil : les masters sont un ajout recent, ne doivent jamais
        -- emporter le releve des executors, qui marche de longue date. Cle
        -- separee "masters", ne touche pas "executors".
        local ok5, mast = pcall(lire_masters)
        d.masters = ok5 and mast or nil
        if not ok5 then
            d.masters_note = "lecture impossible : " .. tostring(mast)
        end
        return d
    end)

    if not ok then
        etat.erreurs = etat.erreurs + 1
        if etat.erreurs <= 3 then
            ErrPrintf("WingBridge : releve impossible - " .. tostring(donnees))
        end
        return
    end

    donnees.erreurs  = etat.erreurs
    donnees.duree_ms = math.floor(((os.clock and os.clock() or 0) - t0) * 1000 + 0.5)

    local ecrit, err = ecrire(encoder(donnees))
    if not ecrit then
        etat.erreurs = etat.erreurs + 1
        if etat.erreurs <= 3 then
            ErrPrintf("WingBridge : ecriture impossible - " .. tostring(err))
        end
    end
end


armer = function(gen)
    Timer(function() releve(gen) end, PERIODE_S, PAR_SALVE,
          function()
              if etat.actif and gen == etat.generation then armer(gen) end
          end)
end


-- Messages en ASCII pur : la ligne de commande de MA3 avale certains
-- caracteres Unicode (tiret cadratin et fleche disparaissaient).
return function()
    if etat.actif then
        etat.actif = false
        etat.generation = etat.generation + 1
        Printf("WingBridge v" .. VERSION .. " : sonde ARRETEE apres " ..
               etat.tours .. " releves, " .. etat.erreurs .. " erreur(s)")
        return
    end

    etat.actif      = true
    etat.tours      = 0
    etat.erreurs    = 0
    etat.generation = etat.generation + 1
    local gen = etat.generation

    Printf("WingBridge v" .. VERSION .. " : sonde DEMARREE, " .. PERIODE_S ..
           " s (generation " .. gen .. ")")
    Printf("WingBridge v" .. VERSION .. " : fichier " .. chemin())
    releve(gen)
    armer(gen)
end
