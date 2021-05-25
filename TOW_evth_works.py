from os.path import join
import ctools
import astropy.units as u
from astropy.time import Time
from astropy.coordinates import SkyCoord
from astropy.io import fits
import argparse
import yaml
import numpy as np
from TOW_functions import append_new_line, irf_selection, read_input_file

parser = argparse.ArgumentParser(description='The significance of a GRB observation is computed at different IRFs according to a visibility table, created with runCatVisibility.py. A configuration YAML file is required, the output is saved as NPY binary file.')
parser.add_argument('-f', '--config', required=True, type=str, help='configuration yaml file')
# configuration file
cf = parser.parse_args().config
# load params configuration from cf
with open(cf) as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)

# -----------------------------------------------Importing variables from yaml configuration file
xml_files_location = cfg['path']['xml_dir']
xml_filename = cfg['path']['xml_filename']
vis_cat_location = cfg['path']['output']
caldb = cfg['ctools']['caldb']
sim_rad = cfg['ctools']['rad']
offset = cfg['ctools']['offset']
sim_e_max = cfg['ctools']['emax']
pointing_delay = cfg['ctools']['pointing_delay']
n = cfg['ctools']['off_regions']

# ------------------------------------------------------------------------generating random seeds
seeds = [601]#np.random.randint(1, 1000, size=cfg['ctools']['iterations'])  # [849,313,923]
# -------------------------------------------------------------------defining some useful paths
catalog = read_input_file(xml_files_location, xml_filename, vis_cat_location)[0]  # location of xml files directories
visibility_table = read_input_file(xml_files_location, xml_filename, vis_cat_location)[1]  # location of visibility table
runids = read_input_file(xml_files_location, xml_filename, vis_cat_location)[2]

# --------------------------------------------------------------reading visibility table
data = np.load(visibility_table, allow_pickle=True, encoding='latin1', fix_imports=True).flat[0]
events = list(data.keys())
sites = list(data[events[0]].keys())
# -------------------------------------------------select input xml model
results = {}
for runid in runids:
    if type(xml_filename) == str:
        inmodel = join(catalog, runid)
    elif xml_filename == None:
        inmodel = runid

    # ------------------------------------------------Running on EVENTS
    for event in events:

        # checking for the event number into the tables
        name = f'{runid.replace(".xml", "")}'
        if name.endswith(str(event)):
            print(f'\nProcessing {event}')
            # reading trigger time from fits file
            results[event]={}
            with fits.open(cfg['path']['catalog'] + f'/{event}.fits') as hdul:
                hdr = hdul[0].header
                t_trigger = Time(hdr['GRBJD'] * u.day, format='jd')
                trigger = float(t_trigger.jd)
            # ----------------------------------------------------Running on SITES

            for site in sites:
                if site == 'North':
                    print(f'\nProcessing site {site}')
                    results[event][site]={}
                    # ----------------------------------------------------Running on NIGHTS
                    for night in data[event][site]:
                        if night == 'night01':
                            print(f'\nProcessing {night}')
                            results[event][site][night]={'irf':[],'t_start':[],  't_stop':[], 'significance':[], 'variance':[]}
                            # ----------------------------------Checking visibility at the site during a specific night
                            if data[event][site][night]['irfs']['zref'][0] == -9.0:
                                print(f'\tThis contains NaNs event---> the source is not observable at the site.')

                                results[event][site][night]['irf'] = -9.0
                                results[event][site][night]['t_start'] = -9.0
                                results[event][site][night]['t_stop'] = -9.0
                                results[event][site][night]['significance'] = -9.0
                                results[event][site][night]['variance'] = -9.0

                            # --------------------------------------------Simulation and analysis of VISIBLE sources
                            else:
                                # ---------------time at which the GRB starts to be visible
                                t_obs_start = data[event][site][night]['irfs']['start'][0]
                                t_obs_start = (t_obs_start - trigger) * 86400
                                # ---------------time at which the GRB stops to be observable
                                t_obs_stop = data[event][site][night]['irfs']['stop'][-1]
                                t_obs_stop = (t_obs_stop - trigger) * 86400

                                # -----------------------start and stop time of the small time slices
                                t_slice_start = t_obs_start + pointing_delay

                                # -----------------------variables that keep memory of counts in previous time slices
                                previous_on = 0.0
                                previous_off = 0.0

                                for j in range(50):
                                    t_slice_stop = t_slice_start + 10 * (j + 2) * np.log10(10 * (j + 2))
                                    # ------------------------arrays that will host counts per seed and sigma per seed
                                    on_counts = np.zeros(shape=len(seeds))
                                    off_counts = np.zeros(shape=len(seeds))
                                    sigma = np.zeros(shape=len(seeds))
                                    for k, seed in enumerate(seeds):
                                        seed = int(seed)
                                        print(f'\nseed number {k + 1}: {seed}')

                                        for i in range(len(data[event][site][night]['irfs']['zref'])):
                                            # -----------------SIMULATION TIMES
                                            zenith_angle = data[event][site][night]['irfs']['zref'][i]
                                            t_min = data[event][site][night]['irfs']["start"][i]
                                            t_max = data[event][site][night]['irfs']["stop"][i]

                                            # converting times from jd to seconds from trigger
                                            irf_t_min = (t_min - trigger) * 86400
                                            irf_t_max = (t_max - trigger) * 86400

                                            if t_slice_stop <= irf_t_min:
                                                continue

                                            if t_slice_start >= irf_t_max:
                                                continue

                                            if irf_t_max - t_slice_stop < t_slice_stop - t_slice_start:
                                                t_slice_stop = irf_t_max

                                            # ----------------------------------------time selection for IRF
                                            delta_t_irf = t_slice_stop - irf_t_min

                                            name_irf = irf_selection(site, zenith_angle, delta_t_irf)[0]
                                            sim_e_min = irf_selection(site, zenith_angle, delta_t_irf)[1]



                                            # ---------------selection of e_min and e_max according  to the irf value

                                            x = np.empty(shape=(n + 1))
                                            y = np.empty(shape=(n + 1))
                                            alpha = 2 * np.pi / (n + 1)

                                            # center of the ON region (centered on the source position as defined in the xml files
                                            x[0] = 0.
                                            y[0] = cfg['ctools']['offset']

                                            # -----------------------------------------------------------------------Simulation
                                            sim = ctools.ctobssim()
                                            sim['inmodel'] = inmodel
                                            sim['caldb'] = caldb
                                            sim['irf'] = name_irf
                                            sim['ra'] = 0.
                                            sim['dec'] = 0.
                                            sim['rad'] = sim_rad
                                            sim['tmin'] = t_slice_start
                                            sim['tmax'] = t_slice_stop
                                            sim['emin'] = sim_e_min
                                            sim['emax'] = sim_e_max
                                            sim['seed'] = seed
                                            sim['outevents'] = 'events_full_GRB.fits'
                                            sim.execute()
                                            # --------------------------------------------------------------------------------------------
                                            print('\n')
                                            print(f'\n\tTime interval: {t_slice_start - t_obs_start}, {t_slice_stop - t_obs_start}')
                                            print(f'\tResponse function: {name_irf}')
                                            # ---------------------------------------------------------------------------------------------
                                            #clear the number of counts per region after each time step
                                            on_reg_counts = 0.0
                                            off_reg_counts = 0.0
                                            # ---------energy steps and corresponding radius( need find a way to generate them automatically )
                                            en_steps=[0.03,0.04,0.562,0.110,0.1778,0.3162,0.5623,1.0,1.7883,3.1623,5.6234,10.0]
                                            reg_rad=[0.35,0.29,0.21,0.16,0.14,0.12,0.095,0.075,0.068,0.061,0.05]
                                            # ---------------------------extracting counts in regions whose radius varies with energy
                                            for m in range(len(en_steps) - 1):
                                                print('\n')
                                                print(f'\tstarting values for inteval {m + 1}: ON - {on_reg_counts} ; OFF - {off_reg_counts}')
                                                # excluding energy ranges below the threshold associated with zenith angle
                                                if en_steps[m] >= sim_e_min:
                                                    r = reg_rad[m]
                                                    print(f'\tregion radius: {r}')
                                                    e_start = en_steps[m]
                                                    e_stop = en_steps[m + 1]
                                                    # print (sim_e_min)
                                                    print(f'\tEnergy interval: {e_start},{e_stop}')
                                                    # print(f'position on:{x[0]},{y[0]}')
                                                    select = ctools.ctselect()
                                                    select['inobs'] = 'events_full_GRB.fits'
                                                    select['usepnt']= False
                                                    select['ra']=x[0]
                                                    select['dec']=y[0]
                                                    select['rad']=r
                                                    select['tmin']=t_slice_start
                                                    select['tmax']=t_slice_stop
                                                    select['emin']=e_start
                                                    select['emax']=e_stop
                                                    select.run()
                                                    on_reg_counts+=select.obs().nobserved()

                                                    print(f'\tCounts in the ON REGION: {on_reg_counts}')

                                                    for reg in range(1, n + 1):
                                                        x[reg] = x[reg - 1] * np.cos(alpha) - y[reg - 1] * np.sin(alpha)
                                                        y[reg] = x[reg - 1] * np.sin(alpha) + y[reg - 1] * np.cos(alpha)

                                                        off_radec = SkyCoord(ra=x[reg] * u.deg, dec=y[reg] * u.deg,frame='fk5')
                                                        off_ra = float(off_radec.ra.deg)
                                                        off_dec = float(off_radec.dec.deg)
                                                        select_off = ctools.ctselect()
                                                        select_off['inobs'] = 'events_full_GRB.fits'
                                                        select_off['usepnt'] = False
                                                        select_off['ra'] = off_ra
                                                        select_off['dec'] = off_dec
                                                        select_off['rad'] = r
                                                        select_off['tmin'] = t_slice_start
                                                        select_off['tmax'] = t_slice_stop
                                                        select_off['emin'] = e_start
                                                        select_off['emax'] = e_stop
                                                        select_off.run()
                                                        off_reg_counts += select_off.obs().nobserved()
                                                        print(f'\tCounts in the OFF region ({x[reg]}, {y[reg]}):{off_reg_counts}')

                                                    r -= np.log10(10) / (12 * (m + 1))

                                        print(f'\t\nCounts in time step {j + 1}:{on_reg_counts},{off_reg_counts}')
                                        print('\n')
                                        a = 1 / n

                                        on_counts[k] = previous_on + on_reg_counts
                                        off_counts[k] = previous_off + off_reg_counts
                                        try:
                                            sigma[k] = 2 * (on_counts[k] * np.log(((1 + a) / a) * (on_counts[k] / (off_counts[k] + on_counts[k]))) + off_counts[k] * np.log((1 + a) * (off_counts[k] / (off_counts[k] + on_counts[k]))))

                                        except ValueError:
                                            continue

                                        if sigma[k] < 0:
                                            sigma[k] = 0
                                        sigma[k] = np.sqrt(sigma[k])
                                    previous_on = np.mean(on_counts)
                                    previous_off = np.mean(off_counts)

                                    var_on = np.std(on_counts)
                                    var_off = np.std(off_counts)
                                    mean_sigma = np.mean(sigma)
                                    var = np.std(sigma)

                                    mean_sigma = round(mean_sigma, 2)
                                    var = round(var, 2)

# -----------------------------------------------------------------------------------------------3 sigma detection

                                    if mean_sigma >=3 and '3sigma' not in results[event][site][night].keys():
                                        results[event][site][night]['3sigma'] = [t_slice_stop,mean_sigma]
                                        if cfg['ctools']['3sigma_stop'] == True:
                                            break
# -----------------------------------------------------------------------------------------------5 sigma detection
                                    if mean_sigma >=5 and '5sigma' not in results[event][site][night].keys():
                                        results[event][site][night]['5sigma'] = [t_slice_stop,mean_sigma]
                                        if cfg['ctools']['5sigma_stop'] == True:
                                            break


                                    #details = (f"{event}, {site}, {night},{t_slice_stop - t_obs_start}, {mean_sigma}, {previous_on}, {previous_off}")
                                    #append_new_line(f'Significance_{event}.txt', details)

                                    print(f'\n\t{event} - site {site} - {night}')
                                    print(f'\tInterval {j + 1}, sim start time: {t_slice_start - t_obs_start}, sim_t_stop: {t_slice_stop - t_obs_start}')
                                    print(f'\tResponse function:{name_irf}, Energy: {sim_e_min} - {sim_e_max}')
                                    print(f'\tTime from trigger: {t_slice_stop}, significance: {mean_sigma}')
                                    print(f'\tOn region counts: {previous_on}, Off region counts: {previous_off}')
                                    print('\n')

                                    results[event][site][night]['irf'].append(name_irf)
                                    results[event][site][night]['t_start'].append(t_slice_start)
                                    results[event][site][night]['t_stop'].append(t_slice_stop)
                                    results[event][site][night]['significance'].append(mean_sigma)
                                    results[event][site][night]['variance'].append(var)

                                    t_slice_start = t_slice_stop
                                    if t_slice_start >= t_obs_stop:
                                        break