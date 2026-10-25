from . import BOX, H, OL, P, TAB, UL

TITLE = r"Σύνοψη, ασκήσεις, γλωσσάριο και βιβλιογραφία"

BLOCKS = [
    H(r"Σύνοψη σε δέκα σημεία"),
    OL(r"Σενάριο = πλήρης, κοινή διαδρομή όλων των αβέβαιων μεγεθών· πιθανότητα = βάρος στο κόστος, όχι συντελεστής "
       r"στους φυσικούς περιορισμούς.",
       r"Στάδιο = χρονικό σημείο απόφασης σε σχέση με την πληροφορία, όχι ώρα του ορίζοντα.",
       r"Οι αποφάσεις πρώτου σταδίου είναι κοινές· οι αποφάσεις προσαρμογής διαφέρουν ανά σενάριο.",
       r"Το στοχαστικό MILP λύνεται ως ένα μεγάλο ντετερμινιστικό ισοδύναμο.",
       r"Ο κώδικας του Codex αντιγράφει το αρχικό μοντέλο ανά σενάριο και επιβάλλει μη προεξόφληση με ισότητες.",
       r"Το μοντέλο δύο σταδίων δίνει στην προσαρμογή πλήρη γνώση της διαδρομής — αισιόδοξο, ιδίως για αποθήκευση.",
       r"Το δέντρο σεναρίων επιβάλλει ίδιες αποφάσεις σε σενάρια με ίδιο ιστορικό· δίνει υλοποιήσιμη εντολή ρίζας.",
       r"WS ≤ RP ≤ EEV· VSS = EEV − RP, EVPI = RP − WS· η VSS εξαρτάται από το ποιες αποφάσεις δεσμεύονται.",
       r"Το CVaR γραμμικοποιείται ακριβώς και τιμωρεί την ουρά της κατανομής κόστους.",
       r"Οι έξοδοι διαχωρίζουν κοινό πρόγραμμα, κατανομές υπό συνθήκη και αναμενόμενα μεγέθη· ο μέσος όρος των σεναρίων "
       r"δεν είναι πρόγραμμα."),
    H(r"Ασκήσεις"),
    OL(r"Στο παράδειγμα της ενότητας 4, αλλάξτε το κόστος ετοιμότητας σε 30 €/MW. Ποιο είναι το νέο $x^\ast$; "
       r"(Υπόδειξη: συμφέρει όσο $80\Pr[N>x]>30$.) Υπολογίστε RP, EEV, VSS.",
       r"Για τρία ισοπίθανα σενάρια, γράψτε ρητά τις ισότητες μη προεξόφλησης για μία μεταβλητή $u_{1,5}$. Πόσες "
       r"χρειάζονται; Γιατί αρκούν $|\mathcal S|-1$;",
       r"Σχεδιάστε ένα δέντρο με `stage_start_hours = [1, 7, 13]` και διακλάδωση 1-2-2. Πόσα σενάρια υπάρχουν; "
       r"Ποιες ώρες έχουν κοινή κατανομή τα σενάρια με ίδιο δεύτερο κόμβο;",
       r"Εκτελέστε το `examples/small_tree_bess.json`, αφαιρέστε το `scenario_tree` και τα `tree_path`, και συγκρίνετε "
       r"το αναμενόμενο κόστος. Γιατί το μοντέλο δύο σταδίων δεν μπορεί να είναι ακριβότερο;",
       r"Υπολογίστε με το χέρι το $\mathrm{CVaR}_{0{,}8}$ της κατανομής της ενότητας 8 και επαληθεύστε με `empirical_cvar()`.",
       r"Στο `small_storage_cvar.json` αυξήστε το `terminal_min_mwh` σε 4. Τι μήνυμα δίνει η επικύρωση; Προσθέστε "
       r"`terminal_shortfall_penalty_eur_per_mwh` και ερμηνεύστε το `nonzero_slacks`.",
       r"Εξηγήστε γιατί στο small_stochastic η VSS με δέσμευση μόνο της ένταξης είναι σχεδόν μηδέν, ενώ με όλο το "
       r"πρώτο στάδιο είναι 3.107,68 €."),
    H(r"Γλωσσάριο"),
    TAB(r"Ελληνικοί και αγγλικοί όροι",
        [r"Ελληνικός όρος", r"Αγγλικός όρος", r"Σύντομη εξήγηση"],
        [[r"Σενάριο", r"Scenario", r"Πλήρης διαδρομή των αβέβαιων δεδομένων"],
         [r"Στάδιο", r"Stage", r"Σημείο απόφασης ως προς την πληροφορία"],
         [r"Απόφαση προσαρμογής", r"Recourse decision", r"Απόφαση μετά την αποκάλυψη"],
         [r"Συνάρτηση προσαρμογής", r"Recourse function $Q(x,\xi)$", r"Βέλτιστο κόστος 2ου σταδίου"],
         [r"Ντετερμινιστικό ισοδύναμο", r"Deterministic equivalent / extensive form", r"Ενιαίο LP/MILP όλων των σεναρίων"],
         [r"Μη προεξόφληση", r"Nonanticipativity", r"Ίδιες αποφάσεις για ίδιο ιστορικό πληροφορίας"],
         [r"Δέντρο σεναρίων", r"Scenario tree", r"Δομή σταδιακής αποκάλυψης πληροφορίας"],
         [r"Πλήρης προσαρμογή", r"Complete recourse", r"Το 2ο στάδιο είναι πάντα εφικτό"],
         [r"Αξία στοχαστικής λύσης", r"VSS", r"EEV − RP"],
         [r"Αναμενόμενη αξία τέλειας πληροφορίας", r"EVPI", r"RP − WS"],
         [r"Υπό συνθήκη αξία σε κίνδυνο", r"CVaR", r"Μέσο κόστος της χειρότερης ουράς"],
         [r"Μείωση σεναρίων", r"Scenario reduction", r"Επιλογή λίγων αντιπροσωπευτικών σεναρίων"],
         [r"Κυλιόμενος ορίζοντας", r"Rolling horizon", r"Επαναλαμβανόμενη επίλυση με νέα πληροφορία"]]),
    H(r"Βιβλιογραφία"),
    UL(r"J. R. Birge, F. Louveaux, *Introduction to Stochastic Programming*, 2η έκδ., Springer, 2011.",
       r"A. Shapiro, D. Dentcheva, A. Ruszczyński, *Lectures on Stochastic Programming: Modeling and Theory*, 3η έκδ., SIAM, 2021.",
       r"P. Kall, S. W. Wallace, *Stochastic Programming*, Wiley, 1994.",
       r"A. J. Conejo, M. Carrión, J. M. Morales, *Decision Making Under Uncertainty in Electricity Markets*, Springer, 2010.",
       r"J. M. Morales, A. J. Conejo, H. Madsen, P. Pinson, M. Zugno, *Integrating Renewables in Electricity Markets*, Springer, 2014.",
       r"R. T. Rockafellar, S. Uryasev, «Optimization of conditional value-at-risk», *Journal of Risk*, 2(3), 2000.",
       r"S. Takriti, J. R. Birge, E. Long, «A stochastic model for the unit commitment problem», *IEEE Trans. Power Systems*, 11(3), 1996.",
       r"H. Heitsch, W. Römisch, «Scenario reduction algorithms in stochastic programming», *Computational Optimization and Applications*, 24, 2003.",
       r"R. T. Rockafellar, R. J.-B. Wets, «Scenarios and policy aggregation in optimization under uncertainty», *Mathematics of Operations Research*, 16(1), 1991.",
       r"*Κώδικας Διαχείρισης Ηλεκτρικών Συστημάτων ΜΔΝ*, 4η έκδοση (Μάρτιος 2022), άρθρα 109 και 111 (εφεδρείες, ισοζύγιο), και Διακήρυξη 512811, ενότητες 5.2.4.3–5.2.4.4.2 (ΚΗΕΠ)· αντίγραφα στο docs/sources."),
    BOX(r"note", r"Τεκμηρίωση του έργου",
        P(r"`docs/stochastic_formulation.md` (πλήρεις εξισώσεις και όρια), `docs/stochastic_mapping.md` (αντιστοίχιση "
          r"ντετερμινιστικού–στοχαστικού), `docs/REVIEW_CHANGES.md` (αλλαγές της αναθεώρησης), "
          r"`docs/verification_report.json` (αριθμητικά αποτελέσματα).")),
]
