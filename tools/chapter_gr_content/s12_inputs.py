from . import BOX, CODE, H, P, TAB, UL

TITLE = r"Είσοδοι του μοντέλου: το αρχείο JSON"

BLOCKS = [
    P(r"Η είσοδος είναι το **υπάρχον** JSON του ντετερμινιστικού MMS, στο οποίο προστίθεται ένα αντικείμενο "
      r"`stochastic`. Έτσι όλα τα τεχνικά δεδομένα (μονάδες, καταστάσεις, κόστη, σημαίες περιορισμών) παραμένουν σε ένα "
      r"μέρος και είναι **κοινά** σε όλα τα σενάρια· μόνο η ζήτηση και η διαθέσιμη ΑΠΕ γίνονται σενάρια."),
    H(r"Ντετερμινιστικό μέρος (κοινό)"),
    TAB(r"Κύρια πεδία του αρχικού JSON",
        [r"Πεδίο", r"Περιεχόμενο", r"Ρόλος στο στοχαστικό μοντέλο"],
        [[r"`Generating_Units[]`", r"Τεχνικά στοιχεία, καμπύλες κόστους, καταστάσεις, μεταβάσεις, χρονιστές, εφεδρείες",
          r"Κοινά· availability γνωστό (χωρίς τυχαίες βλάβες)"],
         [r"`Load_forecast`", r"$H+1$ τιμές, η 0 είναι ιστορικό", r"Η τιμή 0 κοινή· οι 1..H αντικαθίστανται από κάθε σενάριο"],
         [r"`Production_Forecast` (ΑΠΕ)", r"$H$ τιμές ανά μονάδα", r"Αντικαθίσταται από `renewables_mw` κάθε σεναρίου"],
         [r"`current_Power(MW)`, `state`, `isEnabled`", r"Αρχική κατάσταση $t=0$", r"Κοινή, από μέτρηση"],
         [r"`constraints`", r"Σημαίες ενεργοποίησης περιορισμών", r"Ισοζύγιο και μεταβάσεις υποχρεωτικά"],
         [r"`Cost_parameters`, `Other_coefficients`", r"Ποινές, συντελεστές απαιτήσεων εφεδρείας", r"Κοινά"],
         [r"`Time_granularity`", r"Διάρκεια περιόδου σε λεπτά", r"Πρέπει να είναι 60"]]),
    H(r"Το αντικείμενο stochastic"),
    TAB(r"Πεδία του stochastic",
        [r"Πεδίο", r"Υποχρεωτικό", r"Περιεχόμενο"],
        [[r"`scenarios`", r"ναι", r"Λίστα σεναρίων: id, probability, load_mw, renewables_mw, (tree_path)"],
         [r"`slack_policy`", r"ναι", r"mode: legacy ή bounded· caps: ανώτατα όρια χαλαρώσεων ανά πρόθεμα"],
         [r"`scenario_tree`", r"όχι", r"stage_start_hours· ενεργοποιεί το πολυσταδιακό μοντέλο"],
         [r"`risk`", r"όχι", r"alpha, weight (CVaR)· προεπιλογή ουδέτερο ως προς τον κίνδυνο"],
         [r"`reserve_link`, `reserve_link_mode`", r"όχι", r"Σύνδεση παραγωγής–ενεργοποίησης και σημασιολογία της"],
         [r"`reserve_products`", r"με reserve_link", r"response_minutes, κόστη ενεργοποίησης, balancing_deployment"],
         [r"`storage`", r"όχι", r"Λίστα BESS / υβριδικών σταθμών"],
         [r"`cost_policy`", r"όχι", r"thermal_online_charge_eur_per_h, legacy_time_scaled_costs, renewable_curtailment_eur_per_mwh"],
         [r"`maximum_on`", r"όχι", r"Μέγιστος συνεχής χρόνος ON, ιστορικό, προαιρετική ποινή"],
         [r"`initial_operating_obligations`", r"όχι", r"Υπολειπόμενες υποχρεώσεις από κυλιόμενη μετάβαση"]]),
    TAB(r"Πεδία ενός αποθηκευτικού σταθμού (stochastic.storage[])",
        [r"Πεδίο", r"Μονάδα", r"Σημασία"],
        [[r"`capacity_mwh`, `min_mwh`", r"MWh", r"Λειτουργικό εύρος ενέργειας"],
         [r"`initial_mwh`, `terminal_min_mwh`", r"MWh", r"Αρχική (μέτρηση) και ελάχιστη τελική ενέργεια"],
         [r"`charge_mw`, `discharge_mw`", r"MW", r"Όρια ισχύος"],
         [r"`charge_efficiency`, `discharge_efficiency`", r"(0,1]", r"Αποδόσεις"],
         [r"`throughput_eur_per_mwh`", r"€/MWh", r"Κόστος ροής (φθορά) σε φόρτιση και εκφόρτιση"],
         [r"`grid_charge`, `renewable_gen_id`", r"—", r"Φόρτιση από δίκτυο ή μόνο από τη συνδεδεμένη ΑΠΕ"],
         [r"`self_discharge_per_hour`", r"κλάσμα/h", r"Αυτοεκφόρτιση"],
         [r"`terminal_value_eur_per_mwh`", r"€/MWh", r"Αξία ενέργειας στο τέλος του ορίζοντα"],
         [r"`terminal_shortfall_penalty_eur_per_mwh`", r"€/MWh", r"Μαλακός τελικός στόχος"],
         [r"`soc_recovery_penalty_eur_per_mwh`", r"€/MWh", r"Επαναφορά αν η αρχική ενέργεια < ελάχιστο"],
         [r"`max_cycles_per_horizon`", r"κύκλοι", r"Όριο ισοδύναμων πλήρων κύκλων"],
         [r"`export_limit_mw`", r"MW", r"Όριο σημείου σύνδεσης υβριδικού"],
         [r"`power_availability`", r"$H$ κλάσματα", r"Ωριαία διαθεσιμότητα ισχύος"],
         [r"`reserve`", r"—", r"products, sustain_minutes, capacity_cost_eur_per_mw_h"]]),
    H(r"Επικύρωση"),
    P(r"Η `validate()` (`mms/stochastic/data.py`) **δεν επιδιορθώνει** δεδομένα· απορρίπτει με μήνυμα που δείχνει τη "
      r"διαδρομή του λάθους. Ελέγχει μεταξύ άλλων: μήκη χρονοσειρών, πιθανότητες στο $[0,1]$ με άθροισμα 1 (χωρίς "
      r"κανονικοποίηση), μη πεπερασμένους αριθμούς, ΑΠΕ πάνω από τη διαθεσιμότητα (bounded), συνέπεια αρχικής "
      r"κατάστασης, άγνωστα πεδία, συνέπεια του δέντρου, εφικτότητα του τελικού στόχου αποθήκευσης, και ότι η σύνδεση "
      r"εφεδρειών έχει τουλάχιστον ένα ενεργό προϊόν. Το σχήμα `schemas/stochastic_extension.schema.json` περιγράφει "
      r"τη δομή και ένα test εξασφαλίζει ότι συμφωνεί με τον επικυρωτή."),
    CODE(r"""
python stochastic_main.py examples/small_tree_bess.json --validate-only
python stochastic_main.py examples/small_tree_bess.json -o runs/tree.json
python stochastic_main.py examples/small_stochastic.json --compare --evaluation-scenarios examples/held_out_scenarios.json -o runs/comparison.json
""", r"text"),
    BOX(r"note", r"Παραγωγή των παραδειγμάτων",
        P(r"Όλα τα παραδείγματα παράγονται αναπαραγώγιμα με `python tools/make_examples.py` από το αρχικό αρχείο της "
          r"Ρόδου (με σταθερούς σπόρους τυχαιότητας). Είναι συνθετικά, 4 ωρών, για διδακτικούς και ελεγκτικούς σκοπούς — "
          r"όχι λειτουργικά δεδομένα.")),
]
