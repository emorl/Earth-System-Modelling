import pandas as pd
import numpy as np

def prepro(raw_data):
    """ Preprocess data for SWBM
    Convert runoff, latent heat flux and solar net radiation to mm.
    Convert time to date.

    :param raw_data: raw input data (pandas df):
         -snr: surface net radiation
         -tp: total precipitation
         -ro: runoff
         -sm: soil moisture at the surface
         -le: latent heat flux
    :return: pre-processed data (pandas df)
    """

    data = {'time': pd.to_datetime(raw_data['time']),
            'lat': raw_data['latitude'],
            'long': raw_data['longitude'],
            'tp': raw_data['tp_[mm]'],
            'sm': raw_data['sm_[m3/m3]'] * 1000,
            'ro': raw_data['ro_[m]'] * 24000,
            'le': raw_data['le_[W/m2]'] * (86400 / 2260000),
            # 86400 (seconds) / 2260000 (latent heat of vaporization
            # of water in J/kg)
            'snr': raw_data['snr_[MJ/m2]'] * (1 / 2.26),
            }
    return pd.DataFrame(data)

def et(b0, w_i, c_s, g):
    """Compute proportion of maximum ET that occurs given current soil moisture."""
    return b0 * (w_i / c_s) ** g

def runoff(w_i, c_s, a):
    """Compute runoff fraction."""
    return (w_i / c_s) ** a

def predict(curr_moist, evapo, precip, rad, runoff_total):
    """Update soil moisture for next step."""
    return curr_moist + (precip - (evapo * rad) - runoff_total)

def predict_ts(data, config, n_days=None):
    """Run the SMBW for given time series

    :param data: input data (pandas df) (time, tp, sm, ro, le, snr)
    :param config: parameters
                   - water holding capacity (c_s),
                   - maximum of ET function (b0),
                   - ET function shape (g),
                   - runoff function shape (a),
                   - maximum infiltration rate (i_max))
    :param n_days: time series length (default: None)
    :return: soil moisture, runoff, ET (for entire ts) (numpy arrays)
    """
    n_days = data.shape[0] if n_days is None else n_days

    # Initialize arrays for model outputs
    moists, runoffs, runoffs_s, runoffs_h, ets = np.zeros(n_days), np.zeros(n_days), np.zeros(n_days), np.zeros(n_days), np.zeros(n_days)

    # Initial soil moisture (90% of soil water holding capacity)
    moists[0] = 0.9 * config['c_s']
    
    # Parameters
    c_s = config['c_s']
    b0 = config['b0']
    g = config['g']
    a = config['a']
    i_max = config['i_max']
    
    def horton_runoff(precip, i_max):
        """ compute hortonian runoff"""
        return max(0, precip - i_max)

    for i in range(n_days):
        # ET fraction
        ets[i] = et(b0, moists[i], c_s, g)
    
        # saturation runoff
        runoff_frac = runoff(moists[i], c_s, a)
        runoff_s = runoff_frac * data['tp'][i]
        runoffs_s[i] = runoff_s
    
        # Hortonian runoff
        runoff_h = horton_runoff(data['tp'][i], i_max)
        runoffs_h[i] = runoff_h
    
        # total runoff
        runoff_sh = runoff_s + runoff_h
        
        if runoff_sh > data['tp'][i]:
            runoff_s = runoff_s - (runoff_sh - data['tp'][i])
            
        runoff_total = runoff_s + runoff_h
        
        runoffs[i] = runoff_total
    
        # update soil moisture
        if i < n_days - 1:
            moists[i + 1] = predict(
                moists[i],
                ets[i],
                data['tp'][i],
                data['snr'][i],
                runoff_total
            )
    
    # convert ET fraction to flux
    ets = ets * np.asarray(data['snr'])

    return moists, runoffs, ets, runoffs_s, runoffs_h

def model_correlation(data, model_outputs, start=None, end=None):
    """
    Calculate correlation between observed data and model outputs,
    optionally restricted to a timeframe.

    :param data: pandas DataFrame with columns 'sm', 'ro', 'le' (observed)
    :param model_outputs: tuple of numpy arrays (moists, runoffs, ets)
    :param start: str or datetime, start date for analysis (optional)
    :param end: str or datetime, end date for analysis (optional)
    :return: dict with individual correlations and sum of correlations
    """
    moists, runoffs, ets = model_outputs

    # Apply timeframe selection if provided
    if start is not None or end is not None:
        mask = (data['time'] >= pd.to_datetime(start) if start else True) & \
               (data['time'] <= pd.to_datetime(end) if end else True)
        data = data.loc[mask]
        moists = moists[data.index]
        runoffs = runoffs[data.index]
        ets = ets[data.index]

    # Compute correlations
    corr_sm = np.corrcoef(data['sm'], moists)[0, 1]
    corr_ro = np.corrcoef(data['ro'], runoffs)[0, 1]
    corr_et = np.corrcoef(data['le'], ets)[0, 1]

    corr_sum = corr_sm + corr_ro + corr_et

    return {'sm': corr_sm, 'ro': corr_ro, 'et': corr_et, 'sum': corr_sum}
