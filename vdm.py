import os

import pandas as pd
import numpy as np
import tables
import matplotlib.pyplot as plt
from scipy import stats
from iminuit import Minuit
from iminuit.cost import LeastSquares

def gaussian(x, peak, mean, cap_sigma):
    return peak*np.exp(-(x-mean)**2/(2*cap_sigma**2))

os.makedirs('output', exist_ok=True)

data = pd.DataFrame()
with tables.open_file('7525_2110302352_2110310014.hd5', 'r') as f:
    data['timestampsec'] = [r['timestampsec'] for r in f.root.beam.where('timestampsec > 0')]

    collidable = np.nonzero(f.root.beam[0]['collidable'])[0] # indices of colliding

    data['intensity1'] = [r['intensity1'] for r in f.root.beam.where('timestampsec > 0')]
    data['intensity2'] = [r['intensity2'] for r in f.root.beam.where('timestampsec > 0')]

    scan = pd.DataFrame()
    scan['timestampsec'] = [r['timestampsec'] for r in f.root.vdmscan.where('stat == "ACQUIRING"')]
    scan['sep'] = [r['sep'] for r in f.root.vdmscan.where('stat == "ACQUIRING"')]
    scan['nominal_sep_plane'] = [r['nominal_sep_plane'].decode('utf-8') for r in f.root.vdmscan.where('stat == "ACQUIRING"')]
    scan = scan.groupby(['nominal_sep_plane', 'sep']).agg(min_time=('timestampsec', np.min), max_time=('timestampsec', np.max))

    scan.reset_index(inplace=True)

    rates = pd.DataFrame()

    # rate
    for p, plane in enumerate(scan.nominal_sep_plane.unique()):
        for b, sep in enumerate(scan.sep.unique()):
            period_of_scanpoint = f"(timestampsec > {scan.min_time[(scan.nominal_sep_plane == plane) & (scan.sep == sep)].item()}) & (timestampsec <= {scan.max_time[(scan.nominal_sep_plane == plane) & (scan.sep == sep)].item()})"
            
            r = np.array([r['bxraw'][collidable] for r in f.root['pltlumizero'].where(period_of_scanpoint)])
            beam = np.array([b['bxintensity1'][collidable]*b['bxintensity2'][collidable]/1e22 for b in f.root['beam'].where(period_of_scanpoint)])
            new_rates = pd.DataFrame(np.array([r.mean(axis=0), beam.mean(axis=0)]).T, columns=['rate', 'beam'])

            new_rates.insert(0, 'bcid', collidable+1)
            new_rates.insert(0, 'sep', sep)
            new_rates.insert(0, 'plane', plane)

            new_rates['rate_normalised'] = new_rates['rate'] / new_rates['beam']
            new_rates['rate_normalised_err'] = stats.sem(r, axis=0) / new_rates['beam']

            rates = new_rates if p == 0 and b == 0 else pd.concat([rates, new_rates])

    rates.to_csv('output/ratefile.csv', index=False)

    rates['rate_normalised_err'].replace(0, rates['rate_normalised_err'].max(axis=0), inplace=True)

    for p, plane in enumerate(rates.plane.unique()):
        for b, bcid in enumerate(rates.bcid.unique()):
            plt.figure()
            plt.title(f"{plane}, BCID {bcid+1}")
            data_x = scan[scan.nominal_sep_plane == plane]["sep"]
            data_y = rates[(rates.plane == plane) & (rates.bcid == bcid)].rate_normalised
            data_y_err = rates[(rates.plane == plane) & (rates.bcid == bcid)].rate_normalised_err

            least_squares = LeastSquares(data_x, data_y, data_y_err, gaussian)

            m = Minuit(least_squares, peak=1e-4, mean=0, cap_sigma=0.3)

            m.migrad()  # finds minimum of least_squares function
            m.hesse()   # accurately computes uncertainties
            #print(m.values)

            new = pd.DataFrame([m.values, m.errors], columns=m.parameters)
            new.insert(0, 'what', ['value', 'error'])
            new.insert(0, 'plane', plane)
            new.insert(0, 'bcid', bcid)

            fit_results = new if b == 0 and p == 0 else pd.concat([fit_results, new], ignore_index=True)

            plt.errorbar(data_x, data_y, data_y_err, fmt="o")
            x_dense = np.linspace(np.min(data_x), np.max(data_x))
            plt.plot(x_dense, gaussian(x_dense, *m.values))

            fit_info = [f"$\\chi^2$ / $n_\\mathrm{{dof}}$ = {m.fval:.1f} / {len(data_x) - m.nfit}"]

            for param, v, e in zip(m.parameters, m.values, m.errors):
                fit_info.append(f"{param} = ${v:.3e} \\pm {e:.3e}$")

            plt.legend(title="\n".join(fit_info))

            #plt.yscale('log')

            plt.savefig(f'output/fit_{plane}_{bcid}.png')

    fit_results.cap_sigma *= 1e3

    values = fit_results[fit_results.what == 'value']
    errors = fit_results[fit_results.what == 'error']

    xsec = np.pi * values.groupby('bcid').cap_sigma.prod() * values.groupby('bcid').peak.sum()

    print(xsec)
