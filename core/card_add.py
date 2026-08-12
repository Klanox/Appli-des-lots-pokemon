"""Card add and choice popup actions for Pokestock.

Extracted conservatively from app.py. Dependencies are injected from app.py
to preserve existing behavior while reducing app.py size.
"""

import json
import os

from services.custom_card_image_service import apply_custom_image_fallback, resolve_custom_card_image


def configure_card_add(context):
    globals().update(context)


def _compact_number(value):
    value = str(value or "").strip().upper().replace(" ", "")
    if value.isdigit():
        return value.lstrip("0") or "0"
    return value


def _parse_japanese_number_query(value):
    value = str(value or "").strip().replace(" ", "")
    if "/" not in value:
        return value, ""
    local, total = value.split("/", 1)
    return local.strip(), total.strip()


def _number_matches(actual, expected):
    expected = _compact_number(expected)
    if not expected:
        return True
    return _compact_number(actual) == expected


def _collect_total_values(value):
    totals = []
    if isinstance(value, dict):
        for key in ("cardCount", "total", "printedTotal", "official", "cards", "set_total", "total_in_set", "printed_total", "number_total"):
            if key in value:
                totals.extend(_collect_total_values(value.get(key)))
        return totals
    if isinstance(value, (list, tuple)):
        for item in value:
            totals.extend(_collect_total_values(item))
        return totals
    text = str(value or "").strip()
    if text and text.isdigit():
        totals.append(text)
    return totals


def _japanese_candidate_total_values(card):
    values = []
    raw_card = card.get("raw_cache_card") if isinstance(card.get("raw_cache_card"), dict) else {}
    for source in (card, raw_card):
        if not isinstance(source, dict):
            continue
        values.extend(_collect_total_values(source))
        set_info = source.get("set") if isinstance(source.get("set"), dict) else {}
        values.extend(_collect_total_values(set_info))
        for number_key in ("number", "card_number", "localId"):
            raw_number = str(source.get(number_key) or "")
            if "/" in raw_number:
                _, total = _parse_japanese_number_query(raw_number)
                if total:
                    values.append(total)

    deduped = []
    for value in values:
        normalized = _compact_number(value)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _japanese_candidate_matches_total(card, expected_total):
    expected_total = _compact_number(expected_total)
    if not expected_total:
        return True
    return expected_total in _japanese_candidate_total_values(card)


def _popup_candidate_set_id(card_dict):
    set_info = card_dict.get("set")
    if isinstance(set_info, dict):
        return str(set_info.get("id") or "").strip()
    return str(card_dict.get("set_id") or card_dict.get("card_set_id") or "").strip()


def _popup_candidate_number(card_dict):
    raw_card = card_dict.get("raw_cache_card") if isinstance(card_dict.get("raw_cache_card"), dict) else {}
    return str(
        card_dict.get("localId")
        or card_dict.get("number")
        or card_dict.get("card_number")
        or raw_card.get("localId")
        or raw_card.get("number")
        or raw_card.get("card_number")
        or ""
    ).strip()


def _popup_candidate_set_name(card_dict, set_name=""):
    raw_card = card_dict.get("raw_cache_card") if isinstance(card_dict.get("raw_cache_card"), dict) else {}
    for source in (card_dict, raw_card):
        set_info = source.get("set") if isinstance(source.get("set"), dict) else {}
        value = str(set_info.get("name") or source.get("set_name") or source.get("card_set") or "").strip()
        if value:
            return value
    value = str(set_name or "").replace("ðŸ‡¯ðŸ‡µ ", "").replace("🇯🇵 ", "").strip()
    if value:
        return value
    return _popup_candidate_set_id(card_dict)


def _popup_candidate_details_caption(card_dict, set_name=""):
    set_caption = _popup_candidate_set_name(card_dict, set_name)
    number_caption = _popup_candidate_number(card_dict)
    return " · ".join(x for x in [set_caption, f"#{number_caption}" if number_caption else ""] if x)


def _render_popup_candidate_details(card_dict, set_name=""):
    details_caption = _popup_candidate_details_caption(card_dict, set_name)
    if not details_caption:
        return
    st.markdown(
        '<div style="font-size:0.78rem;color:#64748b;text-align:center;'
        f'line-height:1.25;margin-top:-0.25rem;">{html.escape(details_caption)}</div>',
        unsafe_allow_html=True,
    )


def _popup_candidate_image(card_dict):
    images = card_dict.get("images") if isinstance(card_dict.get("images"), dict) else {}
    for value in (
        card_dict.get("image"),
        card_dict.get("imageUrl"),
        card_dict.get("image_url"),
        card_dict.get("image_url_en"),
        images.get("large"),
        images.get("small"),
    ):
        img = str(value or "").strip()
        if not img:
            continue
        if "tcgdex.net" in img and not any(img.endswith(ext) for ext in [".jpg", ".png", ".jpeg", ".webp"]):
            img = f"{img}/high.webp"
        return img

    return resolve_custom_card_image(
        {
            **card_dict,
            "card_id": card_dict.get("card_id") or card_dict.get("id") or "",
            "set_id": _popup_candidate_set_id(card_dict),
            "number": _popup_candidate_number(card_dict),
            "raw_cache_card": card_dict,
        }
    )


def acm_japanese(li, n, sn, num, q, co, p, ir, ie, purchase_price=0., special_tag="", collection_keep=False):
    """Ajouter une carte japonaise — cherche via API JA par nom EN + numéro"""
    if not num:
        return False, "Numéro requis pour les cartes japonaises"
    local_num_query, total_num_query = _parse_japanese_number_query(num)
    local_num_query = local_num_query or num

    # Table de correspondance FR → EN (noms de base des Pokémon)
    FR_TO_EN = {
        "bulbizarre":"bulbasaur","herbizarre":"ivysaur","florizarre":"venusaur",
        "salameche":"charmander","reptincel":"charmeleon","dracaufeu":"charizard",
        "carapuce":"squirtle","carabaffe":"wartortle","tortank":"blastoise",
        "chenipan":"caterpie","chrysacier":"metapod","papilusion":"butterfree",
        "aspicot":"weedle","coconfort":"kakuna","dardargnan":"beedrill",
        "roucool":"pidgey","roucoups":"pidgeotto","roucarnage":"pidgeot",
        "rattata":"rattata","rattatac":"raticate","piafabec":"spearow","rapasdepic":"fearow",
        "abo":"ekans","arbok":"arbok","pikachu":"pikachu","raichu":"raichu",
        "sabelette":"sandshrew","sablaireau":"sandslash","nidoran":"nidoran",
        "nidorina":"nidorina","nidoqueen":"nidoqueen","nidorino":"nidorino",
        "nidoking":"nidoking","melofee":"clefairy","melodelfe":"clefable",
        "goupix":"vulpix","feunard":"ninetales","rondoudou":"jigglypuff",
        "grodoudou":"wigglytuff","nosferapti":"zubat","nosferalto":"golbat",
        "mystherbe":"oddish","ortide":"gloom","rafflesia":"vileplume",
        "paras":"paras","parasect":"parasect","mimitoss":"venonat","aeromite":"venomoth",
        "taupiqueur":"diglett","triopikeur":"dugtrio","miaouss":"meowth",
        "persian":"persian","psyduck":"psyduck","akwakwak":"golduck",
        "machoc":"machop","machopeur":"machoke","mackogneur":"machamp",
        "chetiflor":"bellsprout","boustiflor":"weepinbell","empiflor":"victreebel",
        "tentacool":"tentacool","tentacruel":"tentacruel","racaillou":"geodude",
        "gravalanch":"graveler","grolem":"golem","ponyta":"ponyta","galopa":"rapidash",
        "ramoloss":"slowpoke","flagadoss":"slowbro","magneti":"magnemite",
        "magneton":"magneton","canarticho":"farfetch'd","doduo":"doduo","dodrio":"dodrio",
        "otaria":"seel","lamantine":"dewgong","tadmorv":"grimer","grotadmorv":"muk",
        "kokiyas":"shellder","crustabri":"cloyster","fantominus":"gastly",
        "spectrum":"haunter","ectoplasma":"gengar","onix":"onix","soporifik":"drowzee",
        "hypnomade":"hypno","krabby":"krabby","krabboss":"kingler",
        "voltorbe":"voltorb","electrode":"electrode","noeunoeuf":"exeggcute",
        "noadkoko":"exeggutor","osselait":"cubone","ossatueur":"marowak",
        "kicklee":"hitmonlee","tygnon":"hitmonchan","excelangue":"lickitung",
        "smogo":"koffing","weezing":"weezing","rhinocorne":"rhyhorn",
        "rhinoferor":"rhydon","leveinard":"chansey","saquedeneu":"tangela",
        "kangourex":"kangaskhan","hypotrempe":"horsea","hypocean":"seadra",
        "poissirene":"goldeen","poissoroy":"seaking","stari":"staryu",
        "staross":"starmie","m. mime":"mr. mime","insecateur":"scyther",
        "lippoutou":"jynx","electabuzz":"electabuzz","magmar":"magmar",
        "scarabrute":"pinsir","tauros":"tauros","magicarpe":"magikarp",
        "leviator":"gyarados","lokhlass":"lapras","metamorph":"ditto",
        "evoli":"eevee","aquali":"vaporeon","voltali":"jolteon","pyroli":"flareon",
        "porygon":"porygon","amonita":"omanyte","amonistar":"omastar",
        "kabuto":"kabuto","kabutops":"kabutops","pterapic":"aerodactyl",
        "ronflex":"snorlax","artikodin":"articuno","electhor":"zapdos",
        "sulfura":"moltres","minidraco":"dratini","draco":"dragonair",
        "dracolosse":"dragonite","mewtwo":"mewtwo","mew":"mew",
        # Gen 2
        "germignon":"chikorita","macronium":"bayleef","meganium":"meganium",
        "hericendre":"cyndaquil","feurisson":"quilava","typhlosion":"typhlosion",
        "kaiminus":"totodile","crocrodil":"croconaw","aligatueur":"feraligatr",
        "fouinette":"sentret","fouinar":"furret","hoothoot":"hoothoot",
        "noctowl":"noctowl","ledbiba":"ledyba","ledian":"ledian",
        "arachnie":"spinarak","arigomite":"ariados","nostenfer":"crobat",
        "loupio":"chinchou","lanturn":"lanturn","pichu":"pichu","melopimpin":"cleffa",
        "toudoudou":"igglybuff","togepy":"togepi","togetic":"togetic",
        "natu":"natu","xatu":"xatu","faamelant":"mareep","lainergie":"flaaffy",
        "pharamp":"ampharos","floravol":"bellossom","marill":"marill",
        "azumarill":"azumarill","simularbre":"sudowoodo","ptitard":"politoed",
        "granivol":"hoppip","floravol":"skiploom","cotovol":"jumpluff",
        "granivol":"aipom","motigron":"sunkern","heligon":"sunflora",
        "yanma":"yanma","wattouat":"wooper","maraiste":"quagsire",
        "mentali":"espeon","noctali":"umbreon","laineux":"murkrow",
        "roigada":"slowking","zarbi":"unown","noctunoir":"wobbuffet",
        "girafarig":"girafarig","pomdepik":"pineco","foretress":"forretress",
        "dunsparce":"dunsparce","linoone":"gligar","steelix":"steelix",
        "granbull":"snubbull","hyporoi":"granbull","qwilfish":"qwilfish",
        "cizayox":"scizor","caratroc":"shuckle","heracross":"heracross",
        "snubbull":"snubbull","ursaring":"ursaring","teddiursa":"teddiursa",
        "magmar":"magmar","manta":"mantine","avaltout":"swinub",
        "piloswin":"piloswine","corayon":"corsola","remoraide":"remoraid",
        "octillery":"octillery","cadoizo":"delibird","mantine":"mantine",
        "magnezone":"skarmory","hyporoi":"houndour","demolosse":"houndoom",
        "ymphali":"kingdra","phanpy":"phanpy","donphan":"donphan",
        "porygon2":"porygon2","cerfrousse":"stantler","cadoizo":"smeargle",
        "tygnon":"tyrogue","kicklee":"hitmontop","lippoutou":"smoochum",
        "magby":"magby","minidraco":"miltank","levelard":"blissey",
        "raikou":"raikou","entei":"entei","suicune":"suicune",
        "embrylex":"larvitar","ymphali":"pupitar","tyranocif":"tyranitar",
        "lugia":"lugia","ho-oh":"ho-oh","celebi":"celebi",
        # Gen 3+
        "poussifeu":"torchic","galifeu":"combusken","brasegali":"blaziken",
        "gobou":"mudkip","flobio":"marshtomp","laggron":"swampert",
        "arcko":"treecko","massko":"grovyle","jungko":"sceptile",
        "zigzaton":"zigzagoon","linoone":"linoone","chenipotte":"wurmple",
        "blindalys":"silcoon","armulys":"beautifly","coocyte":"cascoon",
        "papinox":"dustox","lotad":"lotad","lombre":"lombre","ludicolo":"ludicolo",
        "grainipiot":"seedot","pifeuil":"nuzleaf","tengalice":"shiftry",
        "nirondelle":"taillow","hurricane":"swellow","wattouat":"wingull",
        "goelise":"pelipper","chuckfey":"ralts","kirlia":"kirlia",
        "gardevoir":"gardevoir","nincada":"nincada","ninjask":"ninjask",
        "munja":"shedinja","loudred":"loudred","exploud":"exploud","fouinette":"whismur",
        "nounourson":"makuhita","hariyama":"hariyama","azurill":"azurill",
        "tarinor":"nosepass","skitty":"skitty","delcatty":"delcatty",
        "atcham":"sableye","mysdibule":"mawile","aron":"aron","toran":"lairon",
        "galeking":"aggron","meditite":"meditite","medicham":"medicham",
        "dynavolt":"electrike","manectric":"manectric","plusle":"plusle",
        "minun":"minun","illumise":"illumise","volbeat":"volbeat",
        "rosélia":"roselia","boufffant":"gulpin","avaltout":"swalot",
        "carvanha":"carvanha","sharpedo":"sharpedo","wailmer":"wailmer",
        "wailord":"wailord","numel":"numel","chamallot":"camerupt",
        "chartor":"torkoal","spoink":"spoink","groret":"grumpig",
        "kecleon":"kecleon","shuppet":"shuppet","banette":"banette",
        "duskull":"duskull","dusclops":"dusclops","tropius":"tropius",
        "chuchmur":"chimecho","absol":"absol","wynaut":"wynaut",
        "snorunt":"snorunt","glalie":"glalie","spheal":"spheal",
        "phelin":"sealeo","rorqual":"walrein","coquiperl":"clamperl",
        "huntail":"huntail","gorebyss":"gorebyss","relicanth":"relicanth",
        "lovdisc":"luvdisc","draby":"bagon","shelgon":"shelgon",
        "drattak":"salamence","beldepth":"beldum","metang":"metang",
        "metagross":"metagross","regirock":"regirock","regice":"regice",
        "registeel":"registeel","latias":"latias","latios":"latios",
        "kyogre":"kyogre","groudon":"groudon","rayquaza":"rayquaza",
        "jirachi":"jirachi","deoxys":"deoxys",
        # Quelques Gen 4+
        "tortipouss":"turtwig","gauvar":"grotle","torterra":"torterra",
        "ouisticram":"chimchar","chimpenfeu":"monferno","infernape":"infernape",
        "tiplouf":"piplup","empoleon":"empoleon","starly":"starly",
        "étourmi":"staravia","étourvol":"staraptor","kricketot":"kricketot",
        "kricketune":"kricketune","shinx":"shinx","luxio":"luxio","luxray":"luxray",
        "rozbouton":"budew","roserade":"roserade","cranidos":"cranidos",
        "ramboum":"rampardos","dinoclier":"shieldon","bastiodon":"bastiodon",
        "cheniti":"burmy","papinox":"wormadam","papilord":"mothim",
        "apitrini":"combee","apireine":"vespiquen","pachirisu":"pachirisu",
        "phione":"phione","manaphy":"manaphy","darkrai":"darkrai",
        "shaymin":"shaymin","arceus":"arceus","victini":"victini",
        "rhinastoc":"rhyperior","tangrowth":"tangrowth","porygon-z":"porygon-z",
        "togekiss":"togekiss","yanmega":"yanmega","feuforeve":"leafeon",
        "givrali":"glaceon","nostenfer":"gliscor","mammochon":"mamoswine",
        "magnezone":"magnezone","lucario":"lucario","riolu":"riolu",
        "hippopotas":"hippopotas","hippodocus":"hippowdon","scorplane":"skorupi",
        "drascore":"drapion","skorupion":"croagunk","toxicroak":"toxicroak",
        "cradopaud":"carnivine","poissojade":"finneon","lumineon":"lumineon",
        "ninjask":"snover","blizzaroi":"abomasnow","greunoble":"weavile",
        "giratina":"giratina","cresselia":"cresselia","heatran":"heatran",
        "regigigas":"regigigas","dialga":"dialga","palkia":"palkia",
        "giratina":"giratina","uxie":"uxie","mesprit":"mesprit","azelf":"azelf",
        # cartes Trainers/objets courants dans TCG
        "nymphali":"sylveon","mentali":"espeon","noctali":"umbreon",
        "aquali":"vaporeon","pyroli":"flareon","voltali":"jolteon",
        "phyllali":"leafeon","givrali":"glaceon","mucuscule":"goomy",
        "muplodocus":"sliggoo","muplodocus":"goodra","spiritomb":"spiritomb",
        "nidoran♀":"nidoran-f","nidoran♂":"nidoran-m",
        "qulbutoke":"wobbuffet","qulbutoké":"wobbuffet",
    }

    # Trouver le nom EN depuis le nom FR
    # Table de correspondance noms de sets → set_id TCGDex JA
    SET_NAME_TO_ID = {
        "shining darkness": "DP3", "darkness": "DP3",
        "mysterious treasures": "DP2", "space-time creation": "DP1",
        "great encounters": "DP4", "majestic dawn": "DP5",
        "legends awakened": "DP6", "stormfront": "DP7",
        "platinum": "DPt1", "rising rivals": "DPt2",
        "supreme victors": "DPt3", "arceus": "DPt4",
        "heartgold soulsilver": "HGSS1", "unleashed": "HGSS2",
        "undaunted": "HGSS3", "triumphant": "HGSS4",
        "neo genesis": "neo1", "neo discovery": "neo2",
        "neo revelation": "neo3", "neo destiny": "neo4",
        "base set": "base1", "jungle": "base2", "fossil": "base3",
        "team rocket": "base4", "gym heroes": "PMCG1",
        "black white": "BW1", "emerging powers": "BW2",
        "noble victories": "BW3", "next destinies": "BW4",
        "dark explorers": "BW5", "dragons exalted": "BW6",
        "xy": "XY1", "flashfire": "XY2", "furious fists": "XY3",
        "phantom forces": "XY4", "primal clash": "XY5",
        "roaring skies": "XY6", "ancient origins": "XY7",
        "breakthrough": "XY8", "breakpoint": "XY9",
        "fates collide": "XY10", "steam siege": "XY11",
        "evolutions": "XY12", "sun moon": "SM1",
        "guardians rising": "SM2", "burning shadows": "SM3",
        "crimson invasion": "SM4", "ultra prism": "SM5",
        "forbidden light": "SM6", "celestial storm": "SM7",
        "lost thunder": "SM8", "team up": "SM9",
        "unbroken bonds": "SM10", "unified minds": "SM11",
        "cosmic eclipse": "SM12", "sword shield": "S1",
        "rebel clash": "S2", "darkness ablaze": "S3",
        "vivid voltage": "S4", "battle styles": "S5",
        "chilling reign": "S6", "evolving skies": "S7",
        "fusion strike": "S8", "brilliant stars": "S9",
        "astral radiance": "S10", "lost origin": "S11",
        "silver tempest": "S12", "scarlet violet": "SV1",
        "paldea evolved": "SV2", "obsidian flames": "SV3",
        "paradox rift": "SV4", "temporal forces": "SV5",
        "twilight masquerade": "SV6", "stellar crown": "SV7",
        "surging sparks": "SV8", "prismatic evolutions": "SV8a",
        "shiny treasure": "SV4a", "151": "SV2a",
    }
    
    # Convertir sn en set_id si possible
    sn_norm = normalize_name(sn.lower()) if sn else ""
    set_id_filter = None
    if sn_norm:
        for set_name_key, sid in SET_NAME_TO_ID.items():
            if sn_norm in normalize_name(set_name_key) or normalize_name(set_name_key) in sn_norm:
                set_id_filter = sid
                break
        if not set_id_filter:
            set_id_filter = sn  # Utiliser directement si ressemble à un ID

    name_norm = normalize_name(n.lower())
    # Chercher correspondance exacte puis partielle
    name_en = None
    for fr_key, en_val in FR_TO_EN.items():
        if normalize_name(fr_key) == name_norm:
            name_en = en_val
            break
    if not name_en:
        # Recherche partielle
        for fr_key, en_val in FR_TO_EN.items():
            if normalize_name(fr_key) in name_norm or name_norm in normalize_name(fr_key):
                name_en = en_val
                break
    if not name_en:
        name_en = n  # Fallback: utiliser le nom FR tel quel

    try:
        # Chercher par numéro, filtrer par set si fourni
        api_url = f"https://api.tcgdex.net/v2/ja/cards?localId={local_num_query}"
        if set_id_filter:
            api_url = f"https://api.tcgdex.net/v2/ja/sets/{set_id_filter}/cards"
        r = requests.get(api_url, timeout=5)
        candidates = []
        if r.status_code == 200:
            for card in r.json():
                card_num = str(card.get("localId","") or card.get("number",""))
                if not _number_matches(card_num, local_num_query):
                    continue
                if total_num_query and not _japanese_candidate_matches_total(card, total_num_query):
                    continue
                # Filtrer par nom JA si on a une correspondance FR→JA
                # On compare le nom JA de la carte avec le nom anglais trouvé
                card_name_ja = card.get("name","").lower()
                if name_en and name_en != n:
                    # Vérifier si le nom anglais apparaît dans le nom JA (translittération) ou skip si trop différent
                    # Pour l'instant on garde toutes les cartes avec ce numéro
                    pass
                set_info = card.get("set", {})
                set_id = set_info.get("id","") if isinstance(set_info, dict) else ""
                set_name = set_info.get("name","") if isinstance(set_info, dict) else ""
                if sn and sn.lower() not in set_name.lower() and sn.lower() not in set_id.lower():
                    continue
                img = card.get("image","")
                if not img and set_id and card_num:
                    img = f"https://assets.tcgdex.net/ja/{set_id}/{card_num}/high.webp"
                card["image"] = img
                label = f"🇯🇵 {set_id}" + (f" — {set_name}" if set_name else "")
                candidates.append((card, label))

        if not candidates:
            return False, f"Carte JA '{name_en}' #{num} introuvable"

        if len(candidates) == 1:
            ci, si = candidates[0]
            cd = ld()
            nc = ecd(ci, si, lang="ja")
            nc["card_uid"] = new_uid("card")
            nc["quantity"] = q if q else 1
            nc["condition"] = co
            nc["suggested_price"] = p if p else 0.
            nc["is_reverse"] = ir
            nc["is_ed1"] = ie
            nc["name"] = n
            if purchase_price > 0:
                nc["purchase_price"] = purchase_price
            if special_tag:
                nc["special_tag"] = special_tag
            if collection_keep:
                nc["is_collection_keep"] = True
                nc["collection_current_value"] = float(p or 0.)
                nc["collection_purchase_price"] = float(purchase_price or 0.)
            add_or_merge_collection_card(cd, li, nc)
            if cd["lots"][li].get("is_divers"):
                cd["lots"][li]["prix_achat"] = sum(c.get("purchase_price",0.) for c in cd["lots"][li]["cards"])
            sd(cd)
            return True, "Carte japonaise ajoutée !"

        existing = glob.glob(f"popup_{li}_*.json")
        if existing:
            return True, f"{len(candidates)} résultats JA"
        pd = {
            "matches": [[c, s] for c,s in candidates],
            "pending": [n, sn, num, q, co, p, ir, ie, special_tag, collection_keep],
            "search_id": f"{li}_{int(time.time()*1000)}",
            "lang": "ja",
            "name_override": n,
            "pa_carte": purchase_price,
        }
        pf = f"popup_{li}_{int(time.time()*1000)}.json"
        with open(pf, "w") as f:
            json.dump(pd, f)
        return True, f"{len(candidates)} résultats — choisissez le bon set"

    except Exception as e:
        return False, f"Erreur JA: {e}"
        
        if not candidates:
            return False, f"Aucune carte JA avec le numéro {num}"
        
        if len(candidates) == 1:
            ci, si = candidates[0]
            cd = ld()
            nc = ecd(ci, si, lang="ja")
            nc["quantity"] = q if q else 1
            nc["condition"] = co
            nc["suggested_price"] = p if p else 0.
            nc["is_reverse"] = ir
            nc["is_ed1"] = ie
            nc["name"] = n
            if special_tag:
                nc["special_tag"] = special_tag
            if collection_keep:
                nc["is_collection_keep"] = True
                nc["collection_current_value"] = float(p or 0.)
                nc["collection_purchase_price"] = float(purchase_price or 0.)
            add_or_merge_collection_card(cd, li, nc)
            sd(cd)
            return True, "Carte japonaise ajoutée !"
        
        existing = glob.glob(f"popup_{li}_*.json")
        if existing:
            return True, f"{len(candidates)} résultats JA"
        pd = {
            "matches": [[c, s] for c,s in candidates],
            "pending": [n, sn, num, q, co, p, ir, ie, special_tag, collection_keep],
            "search_id": f"{li}_{int(time.time()*1000)}",
            "lang": "ja",
            "name_override": n
        }
        pf = f"popup_{li}_{int(time.time()*1000)}.json"
        with open(pf, "w") as f:
            json.dump(pd, f)
        return True, f"{len(candidates)} sets trouvés — choisissez le bon"
    
    except Exception as e:
        return False, f"Erreur JA: {e}"

def acm(li,n,sn,num,q,co,p,ir,ie,lang="fr",purchase_price=0., special_tag="", collection_keep=False):
    """Ajouter carte au lot"""
    n=n.strip().title()
    sn=sn.strip()
    num=num.strip()
    
    if not n:
        return False,"Nom requis"

    try:
        cd_rule = ld()
        if collection_keep and li < len(cd_rule.get("lots", [])) and cd_rule["lots"][li].get("is_divers"):
            return False, "Les cartes Collection doivent être ajoutées depuis le menu Collection, pas depuis Divers."
    except Exception:
        pass

    # Mode japonais — chercher via API JA avec le set et numéro
    if lang == "ja":
        return acm_japanese(li, n, sn, num, q, co, p, ir, ie, purchase_price=purchase_price, special_tag=special_tag, collection_keep=collection_keep)

    multi=[x.strip().title() for x in n.split(",")]
    
    if len(multi)>1:
        ok_count=0
        for nm in multi:
            if nm:
                lok,lmg=acm(li,nm,sn,num,q,co,p,ir,ie,lang=lang,purchase_price=purchase_price,special_tag=special_tag,collection_keep=collection_keep)
                if lok:
                    ok_count+=1
        return ok_count>0,f"{ok_count} carte(s) ajoutée(s)"
    
    ci,si=afi(n,sn,num)
    
    if not ci:
        ai=sgt(n,num)
        if not ai:
            return False,f"'{n}' introuvable"
        
        
        if len(ai)==1:
            # Chercher les variantes directement dans le cache — sans appeler sgt()
            # pour éviter les appels réseau inutiles
            cards_index = st.session_state.get("cards_index", {})
            suffixes = ["vmax", "v", "ex", "gx", "mega", "tag team", "prime", "lv.x", "break", "legendaire", "légendaire"]
            base_name = normalize_name(n)
            
            seen_ids = set()
            for c,s in ai:
                seen_ids.add(c.get("id",""))
            variantes_uniq = []

            for suffix in suffixes:
                if base_name.endswith(normalize_name(suffix)):
                    continue
                for sep in [" ", "-"]:
                    key = normalize_name(f"{n}{sep}{suffix}".strip())
                    if key in cards_index:
                        for card, set_name, set_id in cards_index[key]:
                            card_num = str(card.get("localId","") or card.get("number",""))
                            matches_num = not num or card_num == num or card_num.zfill(3) == num.zfill(3)
                            if matches_num and card.get("id","") not in seen_ids:
                                seen_ids.add(card.get("id",""))
                                variantes_uniq.append((card, set_name))

            if variantes_uniq:
                # Il y a de vraies variantes différentes — afficher le popup
                all_results = ai + variantes_uniq
                existing_popups = glob.glob(f"popup_{li}_*.json")
                if existing_popups:
                    return True, f"{len(all_results)} résultats"
                sid = f"{li}_{int(time.time()*1000)}"
                pd = {"matches": [[c,s] for c,s in all_results], "pending": [n,sn,num,q,co,p,ir,ie,special_tag,collection_keep], "search_id": sid, "pa_carte": purchase_price}
                pf = f"popup_{li}_{int(time.time()*1000)}.json"
                with open(pf, "w") as f:
                    json.dump(pd, f)
                return True, f"{len(all_results)} résultats"

            # Aucune variante — ajout direct sans popup
            ci,si=ai[0]
        else:
            existing_popups = glob.glob(f"popup_{li}_*.json")
            if existing_popups:
                return True,f"{len(ai)} résultats"
            
            sid=f"{li}_{int(time.time()*1000)}"
            pd={"matches":[[c,s]for c,s in ai],"pending":[n,sn,num,q,co,p,ir,ie,special_tag,collection_keep],"search_id":sid,"pa_carte":purchase_price}
            pf=f"popup_{li}_{int(time.time()*1000)}.json"
            with open(pf,"w")as f:
                json.dump(pd,f)
            return True,f"{len(ai)} résultats"
    
    cd=ld()
    nc=ecd(ci,si,lang=lang)
    apply_custom_image_fallback(nc)
    nc["card_uid"] = new_uid("card")
    nc["quantity"]=q if q else 1
    nc["condition"]=co
    nc["suggested_price"]=p if p else 0.
    nc["is_reverse"]=ir
    nc["is_ed1"]=ie
    if purchase_price > 0:
        nc["purchase_price"] = purchase_price
    if special_tag:
        nc["special_tag"] = special_tag
    if collection_keep:
        nc["is_collection_keep"] = True
        nc["collection_current_value"] = float(p or 0.)
        nc["collection_purchase_price"] = float(purchase_price or 0.)
    add_or_merge_collection_card(cd, li, nc)
    if cd["lots"][li].get("is_divers"):
        cd["lots"][li]["prix_achat"] = sum(c.get("purchase_price",0.) for c in cd["lots"][li]["cards"])
    sd(cd)
    
    return True,"Ajoutée!"

def render_card_choice_popups(li, form_ts_key=None, run_html_func=None):
    popup_files = glob.glob(f"popup_{li}_*.json")
    if not popup_files:
        return

    st.markdown('<div id="card-choice-popup"></div>', unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .choice-card-imgbox {
            height: 170px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #f8fafc;
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            padding: 0.35rem;
            overflow: hidden;
        }
        .choice-card-imgbox img {
            max-width: 100%;
            max-height: 100%;
            width: auto;
            height: auto;
            object-fit: contain;
            border-radius: 9px;
        }
        @media (max-width: 700px) {
            .choice-card-imgbox { height: 130px; padding: 0.25rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if run_html_func is not None:
        run_html_func("""
        <script>
        setTimeout(function() {
            const el = parent.document.getElementById('card-choice-popup');
            if (el) el.scrollIntoView({behavior:'smooth', block:'start'});
        }, 250);
        </script>
        """, height=0)

    for popup_file in popup_files:
        try:
            with open(popup_file, "r", encoding="utf-8") as f:
                popup_data = json.load(f)

            st.warning(f"⚠️ {len(popup_data['matches'])} résultats trouvés — choisissez la bonne carte :")
            popup_lang = popup_data.get("lang", "fr")
            cols = st.columns(min(len(popup_data["matches"]), 4))

            for idx_p, (card_dict, set_name) in enumerate(popup_data["matches"]):
                with cols[idx_p % 4]:
                    img = _popup_candidate_image(card_dict)
                    if img:
                        safe_src = html.escape(proxy_img(img), quote=True)
                        safe_name = html.escape(card_dict.get("name", "Carte"), quote=True)
                        st.markdown(f'<div class="choice-card-imgbox"><img src="{safe_src}" alt="{safe_name}"></div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="choice-card-imgbox">🃏</div>', unsafe_allow_html=True)
                        if popup_lang == "ja":
                            cm_url = html.escape(cardmarket_search_url(card_dict.get("name", "")), quote=True)
                            st.markdown(f'<a href="{cm_url}" target="_blank" style="font-size:0.75rem;color:#3b4cca;text-decoration:none;">🔍 Voir sur Cardmarket</a>', unsafe_allow_html=True)

                    display_name = set_name.replace("🇯🇵 ", "") if popup_lang == "ja" else card_dict.get("name", "")
                    st.caption(f"{display_name}")
                    _render_popup_candidate_details(card_dict, set_name)
                    set_caption = str(set_name or "").replace("ðŸ‡¯ðŸ‡µ ", "").strip()
                    number_caption = _popup_candidate_number(card_dict)
                    details_caption = " · ".join(x for x in [set_caption, f"#{number_caption}" if number_caption else ""] if x)
                    if details_caption:
                        pass

                    if st.button("Choisir", key=f"choose_{popup_file}_{idx_p}"):
                        os.remove(popup_file)
                        pending_vals = list(popup_data.get("pending", []))
                        pending_vals += [""] * (10 - len(pending_vals))
                        n, sn, num, q, co, p, ir, ie, special_tag, collection_keep_pending = pending_vals[:10]
                        name_override = popup_data.get("name_override", "")
                        pa_carte_popup = popup_data.get("pa_carte", 0.)
                        cd_add = ld()
                        if li >= len(cd_add.get("lots", [])):
                            st.error("Lot introuvable pendant l'ajout.")
                            st.rerun()
                        lot_now = cd_add["lots"][li]
                        if lot_now.get("is_divers") and collection_keep_pending:
                            st.error("Les cartes Collection doivent être ajoutées depuis le menu Collection, pas depuis Divers.")
                            st.rerun()

                        nc = ecd(card_dict, set_name, lang=popup_lang)
                        nc["card_uid"] = new_uid("card")
                        nc["quantity"] = q if q else 1
                        nc["condition"] = co
                        nc["suggested_price"] = p if p else 0.
                        nc["is_reverse"] = ir
                        nc["is_ed1"] = ie
                        if name_override:
                            nc["name"] = name_override
                        if lot_now.get("is_divers") and pa_carte_popup > 0:
                            nc["purchase_price"] = pa_carte_popup
                        if special_tag:
                            nc["special_tag"] = special_tag
                        if collection_keep_pending:
                            nc["is_collection_keep"] = True
                            nc["collection_current_value"] = float(p or 0.)
                            nc["collection_purchase_price"] = float(pa_carte_popup or 0.)
                        apply_custom_image_fallback(nc)
                        add_or_merge_collection_card(cd_add, li, nc)
                        if lot_now.get("is_divers"):
                            cd_add["lots"][li]["prix_achat"] = sum(c.get("purchase_price", 0.) for c in cd_add["lots"][li]["cards"])
                        sd(cd_add)
                        if form_ts_key:
                            st.session_state[form_ts_key] = time.time()
                        st.session_state[f"lot_expanded_{li}"] = True
                        st.rerun()
        except Exception:
            try:
                os.remove(popup_file)
            except Exception:
                pass

