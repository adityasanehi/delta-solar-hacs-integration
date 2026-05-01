DOMAIN = "delta_solar"

CONF_PLANT_ID = "plant_id"
CONF_INVERTER_SN = "inverter_sn"
CONF_INVERTER_NUM = "inverter_num"
CONF_TIMEZONE_OFFSET = "timezone_offset"
CONF_PLT_TIMEZONE = "plt_timezone"
CONF_START_DATE = "start_date"
CONF_MTNM = "mtnm"
CONF_PLT_TYPE = "plt_type"
CONF_IS_DST = "is_dst"
CONF_IS_INV = "is_inv"
CONF_PLANT_NAME = "plant_name"
CONF_INVERTER_MODEL = "inverter_model"

BASE_URL = "https://mydeltasolar.deltaww.com"
LOGIN_URL = f"{BASE_URL}/m_gtop"
APP_PAGE_URL = f"{BASE_URL}/app_page.php"
INIT_PLANT_URL = f"{BASE_URL}/web/process_init_plant.php"
AJAX_URL = f"{BASE_URL}/web/AjaxPlantUpdatePlant.php"

DEFAULT_SCAN_INTERVAL = 300  # 5 minutes
