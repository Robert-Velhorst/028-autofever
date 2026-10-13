'use strict';
(() => {
  const pairs = [
    ['Bewerkbare mobiele preview','Editable mobile preview'],['Mijn melding','My notification'],
    ['Autofever · Bewerkbare mobiele preview','Autofever · Editable mobile preview'],['Autofever · Mijn melding','Autofever · My notification'],
    ['Hoofdnavigatie','Main navigation'],['Thuis','Home'],['Profielen','Profiles'],['Personen','People'],['Instellingen','Settings'],
    ['Bewerkbare preview · Er worden geen berichten verstuurd','Editable preview · No messages are sent'],
    ['Instellingen blijven op deze browser opgeslagen','Settings stay saved in this browser'],['Laden…','Loading…'],
    ['Neem de rust','Take the rest'],[' die je nodig hebt.',' you need.'],
    ['Laat je mensen weten hoe het gaat. Met één druk op de knop.','Let your people know how you are. With one press.'],
    ['Ik ben ziek','I am sick'],['Start je ingestelde plan in de preview.','Start your saved plan in the preview.'],
    ['Start je opgeslagen plan op de server.','Start your saved plan on the server.'],['Koppel eerst de server bij Jouw gegevens.','Connect the server in Your details first.'],
    ['Profiel:','Profile:'],['Maak eerst een profiel','Create a profile first'],['Wijzigen','Change'],
    ['Jouw mensen · ','Your people · '],[' ontvangers',' recipients'],['Selecteer ontvangers in je profiel.','Select recipients in your profile.'],
    ['Gereedheidscontrole','Readiness check'],['Ontbrekende gegevens','Missing information'],['Je profiel is ingevuld','Your profile is complete'],
    ['Ontvangers en hulptaken zijn ingesteld.','Recipients and help tasks are set up.'],
    ['Gegevens aanvullen','Complete your details'],['Berichtbezorging is nog niet aangesloten. Je kunt de preview proberen; niemand ontvangt een bericht.','Message delivery is not connected yet. You can try the preview; no one will receive a message.'],
    ['Actieve preview. Deze berichten en taken zijn voorbereid; er is niets verstuurd.','Active preview. These messages and tasks are prepared; nothing has been sent.'],
    ['Berichten aan je mensen','Messages to your people'],['Wat er nodig is','What is needed'],['Beoogde helpers: ','Planned helpers: '],
    ['Geen tijdstip ingesteld','No time set'],['Reserve: ','Backup: '],['Nog niet gevraagd · Niet aangenomen of afgerond','Not requested · Not accepted or completed'],
    ['Geen hulp gevraagd.','No help requested.'],['Verwachte terugkeer: ','Expected return: '],['Check-invoorkeur: elke ','Check-in preference: every '],
    [' uur. Er is geen herinnering gepland.',' hours. No reminder is scheduled.'],['Bewaarde updates','Saved updates'],['Voor: ','For: '],['Niet verstuurd','Not sent'],
    ['Update schrijven','Write an update'],['Ik ben hersteld','I have recovered'],['Gebeurtenis annuleren','Cancel episode'],
    ['Jouw profielen.','Your profiles.'],['Pas per situatie je bericht, mensen en hulpvragen aan.','Tailor your message, people and help requests for each situation.'],
    [' · Standaard',' · Default'],[' hulptaken',' help tasks'],['Bewerken','Edit'],['Als standaard','Set as default'],['Nieuw profiel','New profile'],
    ['Jouw mensen.','Your people.'],['Voeg contacten toe en kies hoe je hen wilt bereiken.','Add contacts and choose how to reach them.'],
    [' · Nog geen bezorgkanaal gekozen',' · No delivery channel chosen'],['Wijzig','Edit'],['Persoon toevoegen','Add person'],['Importeer vCard','Import vCard'],
    ['Een .vcf-bestand wordt eerst hier gecontroleerd. Importeren verstuurt niets, kiest geen bezorgkanaal en voegt niemand aan een profiel toe. Kies pas daarna zelf kanalen en ontvangers.','A .vcf file is reviewed here first. Importing sends nothing, chooses no delivery channel, and adds nobody to a profile. Choose channels and recipients yourself afterwards.'],
    ['Een kleine update.','A small update.'],['Je tekst wordt als concept bewaard.','Your text is saved as a draft.'],['Bericht','Message'],['Voor wie?','For whom?'],
    ['Update bewaren in preview','Save update in preview'],['Terug','Back'],['Fijn dat je','Glad you are'],['weer opknapt.','feeling better.'],
    ['Je herstelbericht voor de ontvangers:','Your recovery message for the recipients:'],['Preview afgesloten. Geen bericht verstuurd.','Preview closed. No message sent.'],['Terug naar thuis','Back home'],
    ['Profiel instellen.','Set up a profile.'],['Stel dit in wanneer je je goed voelt. Publiceer pas als alles klopt.','Set this up while you feel well. Activate only when everything is correct.'],
    ['Je bewaarde concept is hersteld.','Your saved draft has been restored.'],['Wijzigingen worden automatisch als concept bewaard.','Changes are saved automatically as a draft.'],
    ['Naam van het profiel','Profile name'],['Geef je profiel een naam','Name your profile'],['Standaardbericht','Default message'],['Voeg eerst iemand toe bij Personen.','Add someone under People first.'],
    ['Kies wat je nodig hebt en wie kan helpen.','Choose what you need and who can help.'],['Hulptaak toevoegen','Add a help task'],
    ['Alleen informeren, geen hulp vragen','Just inform, do not ask for help'],['Herstelbericht en check-invoorkeur','Recovery message and check-in preference'],
    ['Herstelbericht','Recovery message'],['Verwachte terugkeer (optioneel)','Expected return (optional)'],['Check-invoorkeur: elke … uur','Check-in preference: every … hours'],
    ['Alleen een voorkeur. De preview plant of verstuurt geen herinneringen.','This is only a preference. The preview does not schedule or send reminders.'],
    ['Gebruik als standaardprofiel','Use as the default profile'],['Profiel opslaan','Save profile'],['Terug · concept bewaren','Back · save draft'],
    ['Concept verwerpen','Discard draft'],['Profiel verwijderen','Delete profile'],['Naam','Name'],['Groep','Group'],['Telefoonnummer','Phone number'],['E-mailadres','Email address'],
    ['Via welke kanalen?','Which channels?'],['E-mail vereist een e-mailadres; SMS en WhatsApp een telefoonnummer. Push en andere bezorgdiensten zijn nog niet aangesloten. Er wordt niets verstuurd.','Email requires an email address; SMS and WhatsApp require a phone number. Push and other delivery services are not connected yet. Nothing is sent.'],
    ['Persoon instellen.','Set up a person.'],['Je wijzigingen worden als concept bewaard.','Your changes are saved as a draft.'],['Persoon opslaan','Save person'],['Persoon verwijderen','Delete person'],
    ['Wat is er nodig?','What is needed?'],['Toelichting','Details'],['Wanneer?','When?'],['Herhalen','Repeat'],['Eenmalig','Once'],['Dagelijks','Daily'],['Wekelijks','Weekly'],
    ['Wie kan dit doen?','Who can do this?'],['Selecteer hierboven eerst een ontvanger.','Select a recipient above first.'],['Reservepersoon','Backup person'],['Geen reservepersoon','No backup person'],
    ['Voorkeuren voor deze hulpvraag. De preview herhaalt niets en benadert geen reservepersoon.','Preferences for this help request. The preview does not repeat tasks or contact a backup person.'],['Taak verwijderen','Remove task'],
    ['Jouw gegevens.','Your details.'],['Op deze browser bewaard. Onder jouw controle.','Saved in this browser. Under your control.'],['Wat lokale opslag betekent','What local storage means'],
    ['Deze preview bewaart je gegevens versleuteld op deze browser. De sleutel staat hier ook. Iemand met toegang tot deze geopende browser kan je gegevens lezen.','This preview stores your data encrypted in this browser. The key is stored here too. Anyone with access to this open browser can read your data.'],
    ['Een andere browser of ander websiteadres heeft andere opslag. Bij het wissen van browsergegevens kun je zonder back-up je instellingen verliezen.','A different browser or website address uses different storage. Clearing browser data can erase your settings unless you have a backup.'],
    ['Back-up maken','Create a backup'],['Opgeslagen profielen, contacten, de actieve preview en concepten gaan mee. Gebruik een lange, unieke wachtzin en bewaar die apart. Zonder die wachtzin kunnen we de back-up niet herstellen. Dit is geen inlogcode voor de app.','Saved profiles, contacts, the active preview and drafts are included. Use a long, unique passphrase and store it separately. We cannot restore the backup without it. This is not an app login code.'],
    ['Wachtzin voor back-up','Backup passphrase'],['Herhaal de wachtzin','Repeat the passphrase'],['Minstens 14 tekens; meerdere willekeurige woorden werken prettig.','At least 14 characters; several random words are easy to use.'],
    ['Versleutelde back-up downloaden','Download encrypted backup'],['Back-up terugzetten','Restore a backup'],['We controleren het bestand eerst. Pas na jouw bevestiging worden de huidige gegevens vervangen. Er wordt nooit automatisch een bericht verstuurd.','We check the file first. Current data is replaced only after you confirm. A message is never sent automatically.'],
    ['Back-upbestand','Backup file'],['Wachtzin van de back-up','Backup passphrase'],['Back-up controleren','Check backup'],['Lokale gegevens wissen','Delete local data'],
    ['Typ WIS LOKALE DATA om te bevestigen','Type DELETE LOCAL DATA to confirm'],['Alle Autofever-gegevens op deze browser wissen','Delete all Autofever data in this browser'],
    ['Prettig lezen','Reading preferences'],['Kies wat voor jou werkt. Je kunt beide opties altijd weer uitzetten.','Choose what works for you. You can turn either option off at any time.'],['Grotere tekst','Larger text'],['Hoog contrast','High contrast'],
    ['Automatische bewaartermijn','Automatic retention period'],['Servergegevens exporteren','Export server data'],['Lokale server koppelen','Connect local server'],['Servergegevens wissen','Delete server data'],
    ['Jouw melding.','Your notification.'],['De uitkomst van je laatste actie is nog niet bevestigd. Er wordt geen nieuwe melding gestart.','The outcome of your last action is not confirmed yet. No new notification will be started.'],
    ['Geen verbinding. Je actie is versleuteld op dit apparaat bewaard. Autofever probeert dezelfde actie maximaal 3 keer opnieuw wanneer je weer online bent en Autofever open blijft.','No connection. Your action is saved encrypted on this device. Autofever will retry the same action up to 3 times when you are online again, while Autofever stays open.'],
    ['Automatische pogingen zijn gestopt. Je kunt dezelfde actie veilig opnieuw proberen via Uitkomst controleren.','Automatic attempts have stopped. You can safely retry the same action with Check outcome.'],
    ['Autofever probeert dezelfde actie maximaal 3 keer met wachttijd opnieuw. De serveruitkomst is nog niet bevestigd.','Autofever will retry the same action up to 3 times with a delay. The server outcome is not confirmed yet.'],
    ['Uitkomst controleren','Check outcome'],['Actief op de server.','Active on the server.'],['Herstel vastgelegd op de server.','Recovery recorded on the server.'],['Geannuleerd op de server.','Cancelled on the server.'],
    ['Updatebericht','Update message'],['Ontvangers van deze update','Recipients of this update'],['Nog niemand selecteerbaar: de oorspronkelijke berichten zijn nog niet aangenomen.','No one can be selected yet: the original messages have not been accepted.'],
    ['Concept bewaren slaat je tekst alleen versleuteld op dit apparaat op. Verzenden plaatst één bericht per gekozen persoon in de serverwachtrij. Maximaal 50 updates per ziekmelding; rond de vorige update eerst af.','Save draft stores your text encrypted on this device only. Sending places one message per selected person in the server queue. Maximum 50 updates per episode; finish the previous update first.'],
    ['Update in wachtrij zetten','Queue update'],['Concept bewaren','Save draft'],['Editor sluiten','Close editor'],['Jouw updates','Your updates'],
    ['Status bij de laatste controle. Aangenomen door een bezorgdienst betekent niet bezorgd of gelezen.','Status at last check. Accepted by a delivery service does not mean delivered or read.'],['Berichten','Messages'],
    ['Herstel','Recovery'],['Ziekmelding','Illness notification'],['Onbekende status','Unknown status'],['Lezen expliciet bevestigd','Reading explicitly confirmed'],['Lezen niet bevestigd','Reading not confirmed'],
    ['Hulp','Help'],['Geen hulpvragen ingesteld.','No help requests set up.'],['Aangenomen door ','Accepted by '],['Nog niet aangenomen','Not accepted yet'],['Afgerond','Completed'],['Gesloten','Closed'],
    ['Kan niet helpen: ','Cannot help: '],['Herhaling: ','Repeat: '],['dagelijks','daily'],['wekelijks','weekly'],['bewaard, nog niet ingepland.','saved, not scheduled yet.'],
    ['Reserve: ','Backup: '],['nog niet automatisch gevraagd.','not contacted automatically.'],['Check-in','Check-in'],
    ['Tijd om even bij jezelf in te checken. Dit is alleen zichtbaar in Autofever; er wordt niemand anders bericht.','Time for a check-in. This is visible only in Autofever; nobody else is notified.'],
    ['Ik ben nog ziek · volgende check-in plannen','I am still sick · schedule next check-in'],['Volgende check-in vanaf ','Next check-in from '],[' uur · je bevestiging start de volgende termijn.',' hours · your confirmation starts the next interval.'],
    ['Update schrijven','Write an update'],['Ik ben hersteld','I have recovered'],['Gebeurtenis annuleren','Cancel episode'],['Nieuwe ziekmelding','New illness notification'],['Serverstand ophalen','Refresh server status'],
    ['Pas tekst en ontvangers aan voordat je de herstelmelding in de wachtrij zet. Kies alleen mensen van wie de oorspronkelijke ziekmelding door de bezorgdienst is aangenomen. Dat is geen bewijs van bezorging of lezen.','Edit the message and recipients before queuing the recovery notice. Choose only people whose original illness notice was accepted by the delivery service. This does not prove delivery or reading.'],
    ['Bericht bij herstel','Recovery message'],['Ontvangers van het herstelbericht','Recovery message recipients'],['Geen ontvangers beschikbaar: geen oorspronkelijke ziekmelding is door een bezorgdienst aangenomen.','No recipients are available: no original illness notice was accepted by a delivery service.'],
    ['De herstelmelding sluit deze ziekmelding. Er wordt niets naar andere personen gestuurd.','The recovery notice closes this illness episode. No other people will be contacted.'],['Herstelbericht in wachtrij zetten','Queue recovery notice'],
    ['Je kunt herstel wel vastleggen. Er wordt dan geen herstelbericht in de wachtrij gezet en niemand wordt geïnformeerd.','You can still record your recovery. No recovery notice will be queued and nobody will be notified.'],
    ['Herstel vastleggen zonder bericht','Record recovery without a message'],['Herstel vastgelegd. Er is geen herstelbericht in de wachtrij gezet.','Recovery recorded. No recovery notice was queued.'],
    ['Herstelconcept versleuteld op dit apparaat bewaard. Niets verstuurd.','Recovery draft saved encrypted on this device. Nothing was sent.'],
    ['Schrijf een herstelbericht en selecteer minstens één ontvanger.','Write a recovery message and select at least one recipient.'],
    ['Automatische bewaartermijn','Automatic retention period'],['Standaard staat dit uit. Kies alleen als je wilt dat oude, afgesloten ziekmeldingen en hun servergeschiedenis automatisch uit de live database verdwijnen. Actieve meldingen en berichten met een open, lopende of onzekere bezorgstatus worden nooit opgeruimd. Bewaartermijn werkt pas automatisch wanneer de beheerder de dagelijkse Autofever-opschoontaak op de server heeft ingeschakeld. Exports, serverback-ups en kopieën bij ontvangers vallen hier niet onder.','This is off by default. Choose a period only if you want old, closed illness episodes and their server history automatically removed from the live database. Active episodes and messages with open, running or uncertain delivery status are never removed. Retention runs automatically only after the administrator enables Autofever’s daily cleanup task on the server. Exports, server backups and recipient copies are not covered.'],
    ['Bewaar geschiedenis na afsluiten (dagen; leeg = uit)','Keep history after closure (days; blank = off)'],['1 tot 3650 dagen. Een kortere termijn kan bij de eerstvolgende dagelijkse opschoningsrun direct geschiedenis verwijderen.','1 to 3650 days. A shorter period can remove history at the next daily cleanup run.'],['Bewaartermijn opslaan','Save retention period'],
    ['Dit bevat je serverhistorie: ziekte- en herstelberichten, contactgegevens, helperstatus en check-ins. De download wordt eerst met een aparte wachtzin versleuteld. Bewaar die wachtzin los van het bestand. Dit exporteert niet je lokale profielen; gebruik daarvoor de gewone Autofever-back-up.','This contains your server history: illness and recovery messages, contact details, helper status and check-ins. The download is encrypted with a separate passphrase. Store that passphrase separately from the file. This does not export local profiles; use the regular Autofever backup for those.'],
    ['Wachtzin voor de serverexport','Server export passphrase'],['Minstens 14 tekens. De wachtzin wordt niet opgeslagen of naar de server gestuurd.','At least 14 characters. The passphrase is not stored or sent to the server.'],['Versleutelde serverexport downloaden','Download encrypted server export'],
    ['Eenmalige privésleutel van de beheerder, geen nieuw account. Alleen deze server op dit adres. Bewaar de sleutel apart; de profielback-up bevat hem niet. De sleutel wordt hier versleuteld opgeslagen, met de browsersleutel op hetzelfde apparaat.','One-time private key from the administrator, not a new account. Only this server at this address. Store the key separately; the profile backup does not include it. The key is stored encrypted here, with the browser key on this same device.'],
    ['Privésleutel voor jouw meldingen','Private key for your notifications'],['Geldigheid hulplink in uren','Helper-link validity in hours'],['Koppeling controleren en bewaren','Check and save connection'],
    ['Terugzetten van een profielback-up wijzigt geen lopende servermelding. Meerdere kanalen per persoon en push zijn nog niet aangesloten; kies voor deze koppeling één beginkanaal.','Restoring a profile backup does not change an ongoing server notification. Multiple channels per person and push are not connected yet; choose one initial channel for this connection.'],
    ['Dit verwijdert je live serverhistorie: ziekte- en herstelteksten, contactgegevens, helpers, check-ins en de berichtenwachtrij. Klaarstaande berichten worden verwijderd; eerder bezorgde berichten kunnen niet worden teruggehaald. Je lokale profielen en serverkoppeling blijven bewaard. Gegevens in operatorback-ups of bij ontvangers worden niet door deze actie gewist.','This deletes your live server history: illness and recovery text, contact details, helpers, check-ins and queued messages. Queued messages are deleted; messages already delivered cannot be recalled. Your local profiles and server connection remain. This does not delete operator backups or recipient copies.'],
    ['Typ VERWIJDER MIJN SERVERGEGEVENS om te bevestigen','Type DELETE MY SERVER DATA to confirm'],['Niet mogelijk zolang een verzending bezig is of een provideruitkomst onzeker is; die moet eerst worden opgelost.','Unavailable while a send is in progress or a provider outcome is uncertain; resolve that first.'],['Alle servergegevens verwijderen','Delete all server data'],
    ['Lokale serverkoppeling · echte bezorgdiensten nog niet aangesloten','Local server connection · real delivery services are not connected yet'],
    ['De server bewaart de melding en wachtrij. Zonder bezorgdienst worden er geen berichten verstuurd. Check-ins zijn zichtbaar zodra je Autofever opent; herhaalde hulp en reservehelpers zijn nog niet geautomatiseerd.','The server stores the notification and queue. No messages are sent without a delivery service. Check-ins appear when you open Autofever; recurring help and backup helpers are not automated.'],
    ['Kies vooraf per ontvanger één kanaal: e-mail, SMS of WhatsApp. Meerdere kanalen en push vereisen nog een aparte bezorginstelling.','Choose one channel per recipient in advance: email, SMS or WhatsApp. Multiple channels and push still require separate delivery setup.'],
    ['Dit verwijdert Autofever-profielen, contacten, concepten, de lokale serverkoppeling en de versleutelingssleutel uit deze browser. Het verwijdert niets van de server, uit gedownloade back-ups of bij eerdere ontvangers.','This deletes Autofever profiles, contacts, drafts, the local server connection and the encryption key from this browser. It does not delete anything from the server, downloaded backups or previous recipients.'],
    ['Koppeling gecontroleerd en bewaard. Er is niets verstuurd.','Connection checked and saved. Nothing was sent.'],
    ['Je bevestiging start de volgende termijn.','Your confirmation starts the next interval.'],
    ['In wachtrij · niet verstuurd','Queued · not sent'],['Wordt aangeboden · uitkomst nog onbekend','Submitting · outcome not yet known'],
    ['Aangenomen door de bezorgdienst · bezorging niet bevestigd','Accepted by delivery service · delivery not confirmed'],
    ['Niet verstuurd · mislukt','Not sent · failed'],['Verzenduitkomst onzeker · controle nodig','Delivery outcome uncertain · check required'],
    ['Geannuleerd · niet verstuurd','Cancelled · not sent'],['Lokale serverkoppeling · echte bezorgdiensten nog niet aangesloten','Local server connection · real delivery services are not connected yet'],
    ['Koppeling gecontroleerd en bewaard. Er is niets verstuurd.','Connection checked and saved. Nothing was sent.'],
    ['Serverstand bijgewerkt. Een wachtrijstatus is geen bewijs van bezorging.','Server status updated. A queue status is not proof of delivery.'],
    ['Serverhistorie gewist. Je lokale profielen en serverkoppeling zijn behouden.','Server history deleted. Your local profiles and server connection are unchanged.'],
    ['Huidige opgeslagen gegevens en concepten vervangen door deze back-up? Download eerst een back-up als je ze wilt bewaren. Er wordt niets verstuurd.','Replace the current saved data and drafts with this backup? Download a backup first if you want to keep them. Nothing will be sent.'],
    ['Dit concept verwerpen? Je opgeslagen profiel of contact blijft ongewijzigd.','Discard this draft? Your saved profile or contact will remain unchanged.'],
    ['Dit profiel verwijderen?','Delete this profile?'],['Deze persoon en diens koppelingen uit je profielen verwijderen?','Remove this person and their links from your profiles?'],
    ['Alle Autofever-profielen, contacten, concepten en de serverkoppeling uit deze browser wissen? Servergegevens en losse back-upbestanden blijven bestaan.','Delete all Autofever profiles, contacts, drafts and server connection from this browser? Server data and separate backup files will remain.'],
    ['Typ de bevestiging exact over om lokale gegevens te wissen.','Type the confirmation exactly to delete local data.'],
    ['Lokale gegevens konden niet volledig worden gewist. Herlaad niet; probeer opnieuw of wis de sitegegevens via je browser.','Local data could not be fully deleted. Do not reload; try again or clear this site’s data in your browser.'],
    ['Deze kortere bewaartermijn kan bij de volgende dagelijkse serveropschoning oude, afgesloten geschiedenis definitief uit de live database verwijderen. Back-ups en ontvangerkopieën blijven bestaan. Doorgaan?','This shorter retention period may permanently remove old, closed history from the live database during the next daily server cleanup. Backups and recipient copies remain. Continue?'],
    ['Alle live serverepisoden, contactgegevens, helperreacties, check-ins en wachtrijberichten voor deze eigenaar wissen? Lokale profielen blijven bestaan; al bezorgde berichten en operatorback-ups niet.','Delete all live server episodes, contact details, helper responses, check-ins and queued messages for this owner? Local profiles will remain; messages already delivered and operator backups will not be deleted.'],
  ];
  const nlToEn = new Map(pairs), enToNl = new Map(pairs.map(([nl, en]) => [en, nl]));
  const key = 'autofever-language';
  let locale = 'nl';
  try { locale = localStorage.getItem(key) === 'en' ? 'en' : 'nl'; } catch { /* language control remains usable for this page */ }
  const language = () => locale;
  function mapText(value, target) {
    const source = target === 'en' ? nlToEn : enToNl;
    const direct = source.get(value);
    if (direct) return direct;
    const trimmed=value.trim(),surrounding=source.get(trimmed);
    if (surrounding) return value.slice(0,value.indexOf(trimmed))+surrounding+value.slice(value.indexOf(trimmed)+trimmed.length);
    let result = value;
    const rules = target === 'en' ? [
      [/^(\d+) ontvangers$/, '$1 recipients'], [/^(\d+) hulptaken$/, '$1 help tasks'],
      [/^Hulptaak (\d+)$/, 'Help task $1'], [/^Profiel (.+)$/, 'Profile $1'],
      [/^\+ (\d+) uur$/, '+ $1 hours'], [/^(.+) gevonden · (\d+) bestaand of dubbel · (\d+) geselecteerd\..*$/, '$1 found · $2 existing or duplicate · $3 selected. Importing does not choose a delivery channel or add anyone to a profile.'],
      [/^Importeer (\d+) (contact|contacten)$/, 'Import $1 contact$2'],
      [/^Aangenomen door (.+)$/, 'Accepted by $1'],
      [/^Koppeling bewaard\. Verlopen hulplinks sluiten na (\d+) uur\.$/, 'Connection saved. Expired helper links close after $1 hours.'],
      [/^Elke (\d+) uur · je bevestiging start de volgende termijn\.$/, 'Every $1 hours · your confirmation starts the next interval.'],
      [/^Herhaling: (dagelijks|wekelijks) · bewaard, nog niet ingepland\.$/, (_,frequency)=>`Repeat: ${frequency==='dagelijks'?'daily':'weekly'} · saved, not scheduled yet.`],
      [/^Reserve: (.+) · nog niet automatisch gevraagd\.$/, 'Backup: $1 · not contacted automatically.'],
    ] : [
      [/^(\d+) recipients$/, '$1 ontvangers'], [/^(\d+) help tasks$/, '$1 hulptaken'],
      [/^Help task (\d+)$/, 'Hulptaak $1'], [/^Profile (.+)$/, 'Profiel $1'],
      [/^\+ (\d+) hours$/, '+ $1 uur'],[/^Accepted by (.+)$/, 'Aangenomen door $1'],
      [/^Connection saved\. Expired helper links close after (\d+) hours\.$/, 'Koppeling bewaard. Verlopen hulplinks sluiten na $1 uur.'],
      [/^Every (\d+) hours · your confirmation starts the next interval\.$/, 'Elke $1 uur · je bevestiging start de volgende termijn.'],
      [/^Repeat: (daily|weekly) · saved, not scheduled yet\.$/, (_,frequency)=>`Herhaling: ${frequency==='daily'?'dagelijks':'wekelijks'} · bewaard, nog niet ingepland.`],
      [/^Backup: (.+) · not contacted automatically\.$/, 'Reserve: $1 · nog niet automatisch gevraagd.'],
    ];
    for (const [pattern, replacement] of rules) result = result.replace(pattern, replacement);
    return result;
  }
  function excluded(node) {
    return !!node.parentElement?.closest('.wordmark,.avatar,.face,.long,.message-preview,.compact-heading:not(#owner-title),.profile-summary h2,.profile-option strong,.row strong,.row small,.editor-block h3,.task-block h3,.task-block strong,.profile-link strong,.check span,#section-message [data-summary],textarea,input,select option:not([value=""]):not([value="once"]):not([value="daily"]):not([value="weekly"]),[data-i18n-skip]');
  }
  function translateTextNode(node) {
    if (!node?.isConnected || excluded(node)) return;
    const before = node.data, after = mapText(before, locale);
    if (after !== before) node.data = after;
  }
  function localize(root = document) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(translateTextNode);
    const title = document.querySelector('title');
    if (title) title.textContent = mapText(title.textContent, locale);
    const nav = document.querySelector('nav[aria-label]');
    if (nav) nav.setAttribute('aria-label', mapText(nav.getAttribute('aria-label'), locale));
    for (const el of root.querySelectorAll?.('[aria-label],[placeholder],[title]') || []) {
      for (const attr of ['aria-label','placeholder','title']) if (el.hasAttribute(attr)) el.setAttribute(attr, mapText(el.getAttribute(attr), locale));
    }
    document.documentElement.lang = locale;
  }
  function setLocale(value) {
    locale = value === 'en' ? 'en' : 'nl';
    try { localStorage.setItem(key, locale); } catch { /* keep the in-page choice */ }
    const toggle = document.getElementById('language-toggle');
    if (toggle) {
      toggle.textContent = locale === 'en' ? 'Nederlands' : 'English';
      toggle.lang = locale === 'en' ? 'nl' : 'en';
      toggle.setAttribute('aria-label', locale === 'en' ? 'Switch language to Dutch' : 'Switch language to English');
    }
    localize();
  }
  function toggle() { setLocale(locale === 'nl' ? 'en' : 'nl'); }
  document.addEventListener('click', event => {
    if (event.target.closest('#language-toggle')) { event.preventDefault(); toggle(); }
  });
  document.addEventListener('DOMContentLoaded', () => {
    setLocale(locale);
    const root = document.querySelector('.app') || document.body;
    new MutationObserver(records => {
      for (const record of records) {
        if (record.type === 'characterData') translateTextNode(record.target);
        for (const node of record.addedNodes || []) {
          if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
          else if (node.nodeType === Node.ELEMENT_NODE) localize(node);
        }
      }
    }).observe(root, {subtree:true,childList:true,characterData:true});
  }, {once:true});
  window.AutofeverLocale = {get:language,set:setLocale,toggle,translate:value=>mapText(value,locale),localize};
})();
