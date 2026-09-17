-- ===========================================================================
--  Wing Bridge - amorce de chargement
-- ===========================================================================
--
--  POURQUOI
--  MA3 garde en memoire le code Lua deja charge. Verifie :
--  ni ReloadAllPlugins, ni la bascule Installed No/Yes, ni un arret du plugin
--  ne le remplacent. Seul un redemarrage de MA3 ou un re-import le fait —
--  inacceptable comme boucle de mise au point, et impossible a distance.
--
--  CE QUE FAIT CETTE AMORCE
--  Elle ne contient AUCUNE logique : a chaque appel, elle relit
--  wingbridge.lua sur le disque et execute ce qu'il rend. Une fois cette
--  amorce importee, toute nouvelle version de la sonde prend effet au
--  prochain "Plugin N" — sans ReloadAllPlugins, sans re-import, sans
--  redemarrage.
--
--  Elle est volontairement minuscule et ne devrait jamais changer. Si elle
--  doit changer un jour, il faudra la re-importer une fois.
--
--  INSTALLATION (une seule fois)
--    Edit Plugin 3  -> Import -> wingloader
--    Set Plugin 3.1 Property "Installed" "Yes"
--    Plugin 3       -> lance la sonde (bascule marche/arret)
--    Puis ENREGISTRER LE SHOW.
-- ===========================================================================

local CIBLE = "datapools/plugins/wingbridge.lua"


local function chemin()
    local base = GetPath(Enums.PathType.Library)
    local sep = "/"
    if GetPathSeparator then sep = GetPathSeparator() end
    return base .. sep .. CIBLE:gsub("/", sep)
end


return function(...)
    local c = chemin()

    -- Deux voies : loadfile s'il existe, sinon lecture io + load. On ne
    -- suppose pas lequel MA3 autorise — on essaie, et on dit lequel a servi
    -- si les deux echouent.
    local chunk, err
    if loadfile then
        chunk, err = loadfile(c)
    end
    if not chunk then
        local f = io.open(c, "r")
        if not f then
            ErrPrintf("WingLoader : fichier introuvable - " .. c)
            ErrPrintf("WingLoader : loadfile a dit : " .. tostring(err))
            return
        end
        local texte = f:read("*a")
        f:close()
        chunk, err = load(texte, "@" .. c)
    end
    if not chunk then
        ErrPrintf("WingLoader : compilation impossible - " .. tostring(err))
        return
    end

    local ok, fn = pcall(chunk)
    if not ok then
        ErrPrintf("WingLoader : execution impossible - " .. tostring(fn))
        return
    end
    if type(fn) ~= "function" then
        ErrPrintf("WingLoader : le fichier n'a pas rendu de fonction (" ..
                  type(fn) .. ")")
        return
    end
    return fn(...)
end
