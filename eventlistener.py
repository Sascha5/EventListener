
from threading import Thread
import time

from web3 import Web3
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

from abi import abi_diva_factory, abi_erc_20

BLOCK_START_HISTORIC_DATA = 10634132  # 10818010 #10539836 
provider_url = "https://ropsten.infura.io/v3/17bef66786014323915d3df8e080eb84"

web3 = Web3(Web3.HTTPProvider(provider_url)) 

address_diva_factory = "0x30d9151B554950BB19331bC42a6C6d09B902003A"

diva_factory_contract = web3.eth.contract(address=address_diva_factory, abi=abi_diva_factory)

cred_firebase = credentials.Certificate('divaprotocoltest-firebase-adminsdk-vtkug-6a2429d9e1.json')
firebase_admin.initialize_app(cred_firebase)

db_firstore = firestore.client()

def write_event_to_database(option_parameters, expiry_parameters, event, bln_new_option):

    def write_dict_to_database(table_name, dict_to_write):
        doc_ref = db_firstore.collection(table_name).document()
        doc_ref.set(dict_to_write)
        
    contract_collateral_token = web3.eth.contract(address=option_parameters[7], abi=abi_erc_20)
    decimals_collateral_token = contract_collateral_token.functions.decimals().call()
    name_collateral_token = contract_collateral_token.functions.name().call()
    
    decimal_factor = 10 ** 18
    decimal_factor_collateral = 10 ** decimals_collateral_token
    # only add static parameters for issue option events
    
    if bln_new_option:
        # split in two entries to make it easier in the frontend
        
        # add put option (short token)
        dict_option_db_entry = {"OptionSetId":  event["args"]["optionId"],
                                 "ReferenceAsset": option_parameters[0],
                                 "ExpiryDate": option_parameters[6],
                                 "CollateralToken": option_parameters[7],
                                 "CollateralTokenName": name_collateral_token,
                                 "DecimalsCollateralToken": decimals_collateral_token,
                                 "RedemptionFee": expiry_parameters[6] / decimal_factor,
                                 "SettlementFee": expiry_parameters[7] / decimal_factor,
                                 "DataFeedProvider": expiry_parameters[5],
                                 "DataFeedProviderIsWhitelisted": True,
                                 "DataFeedProviderName": "DIVA",
                                 "Inflection": option_parameters[1] / decimal_factor,
                                 "BlockNumber": event["blockNumber"]
                                 }
        
        # inflection option_parameters[1]
        # cap option_parameters[2]
        # floor option_parameters[3]
        
        strike_call = option_parameters[3]
        strike_put = option_parameters[2] 
            
        # overwrite special cases
        # short pool not funded 
        if option_parameters[8] == 0: 
            strike_put = option_parameters[1]
        # long pool not funded
        elif option_parameters[9] == 0:
            strike_call = option_parameters[1]

        floor = strike_call
        cap = strike_put 
        
        dict_put_db_entry = {"TokenAddress": option_parameters[10],
                              "IsLong": False,
                              "Strike": strike_put / decimal_factor,
                              "Cap": floor / decimal_factor,
                              "OptionId": "S-" + str(event["args"]["optionId"])}
        
        dict_call_db_entry = {"TokenAddress": option_parameters[11],
                                "IsLong": True,
                                "Strike": strike_call / decimal_factor,
                                "Cap": cap / decimal_factor,
                                "OptionId": "L-" + str(event["args"]["optionId"])}
                
        write_dict_to_database("T_Options_New", {**dict_option_db_entry, **dict_put_db_entry})
        write_dict_to_database("T_Options_New", {**dict_option_db_entry, **dict_call_db_entry})

    dict_liquidity_db_entry = {"OptionSetId" : event["args"]["optionId"],
                               "SupplyShort": option_parameters[4] / decimal_factor,
                               "SupplyLong": option_parameters[5] / decimal_factor,
                               "CollateralBalanceShort": option_parameters[8] / decimal_factor_collateral,
                               "CollateralBalanceLong": option_parameters[9] / decimal_factor_collateral,
                               "BlockNumber": event["blockNumber"]}
    
    dict_settlement_db_entry = {"OptionSetId" : event["args"]["optionId"],
                                "FinalReferencePrice" : expiry_parameters[0] / decimal_factor,
                                "StatusFinalReferencePrice" : expiry_parameters[1],
                                "RedemptionAmountLongToken": expiry_parameters[2] / decimal_factor,
                                "RedemptionAmountShortToken": expiry_parameters[3] / decimal_factor,
                                "StatusTimeStamp": expiry_parameters[4],
                                "BlockNumber": event["blockNumber"]}
            
    write_dict_to_database("T_Events_Liquidity_New", dict_liquidity_db_entry)
    write_dict_to_database("T_Events_Settlement_New", dict_settlement_db_entry)


def log_loop(event_filter, poll_interval, new_option):
     # to avoid duplicated entries
    last_checked_block = BLOCK_START_HISTORIC_DATA

    while True:
        try:
            latest_block = web3.eth.blockNumber
            if latest_block > last_checked_block:
                for event in event_filter.get_new_entries():
                    
                    option_parameters = diva_factory_contract.functions.getOptionParametersById(event["args"]["optionId"]).call()
                    expiry_parameters = diva_factory_contract.functions.getExpiryParametersById(event["args"]["optionId"]).call()
                    
                    write_event_to_database(option_parameters, expiry_parameters, event, new_option)
        except Exception as e:
            print(e)
        finally:
            last_checked_block = latest_block
        time.sleep(poll_interval)  # what if two blocks were created since last poll ?

def main():
    #CheckedBlocks_ref = db_firstore.collection(u'CheckedBlocks')
    # Create a query against the collection
    #query_ref = CheckedBlocks_ref.where(u'BlockNumber', u'==', u'10634132')

    #===========================================================================
    # issue option
    #===========================================================================
    event_filter_options = diva_factory_contract.events.OptionIssued.createFilter(fromBlock=BLOCK_START_HISTORIC_DATA)  
    all_historic_issue_options_events = event_filter_options.get_all_entries()
    
    # write historic data to database (assume db is empty)
    for event in all_historic_issue_options_events:
        option_parameters = diva_factory_contract.functions.getOptionParametersById(event["args"]["optionId"]).call()
        expiry_parameters = diva_factory_contract.functions.getExpiryParametersById(event["args"]["optionId"]).call()
        
        write_event_to_database(option_parameters, expiry_parameters, event, True)
            
    #===========================================================================
    # Expiry status changed
    #===========================================================================
    event_filter_status_changed = diva_factory_contract.events.StatusChanged.createFilter(fromBlock=BLOCK_START_HISTORIC_DATA)  
    all_historic_status_changed_events = event_filter_status_changed.get_all_entries()
    
    # write historic data to database (assume db is empty)
    for event in all_historic_status_changed_events:
        option_parameters = diva_factory_contract.functions.getOptionParametersById(event["args"]["optionId"]).call()
        expiry_parameters = diva_factory_contract.functions.getExpiryParametersById(event["args"]["optionId"]).call()
        
        write_event_to_database(option_parameters, expiry_parameters, event, False)

    # start loop that check for new OptionIssued events
    event_filter_option_issued = diva_factory_contract.events.OptionIssued.createFilter(fromBlock='latest')  # what if two blocks were created since last poll ?
    thread_option_issued = Thread(target=log_loop, args=(event_filter_option_issued, 4, True,))
    # log_loop(event_filter_option_issued, 2)

    # start loop that check for new OptionIssued events
    event_filter_status_changed = diva_factory_contract.events.StatusChanged.createFilter(fromBlock='latest')  # what if two blocks were created since last poll ?
    thread_status_changed = Thread(target=log_loop, args=(event_filter_status_changed, 4, False,))

    thread_option_issued.start()
    thread_status_changed.start()
    
    thread_option_issued.join()
    thread_status_changed.join()

if __name__ == '__main__':
    main()

