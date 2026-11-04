frappe.listview_settings['Hns Face Detection Log'] = {
    onload: function(listview) {
        listview.page.clear_primary_action();
        
        setTimeout(() => {
            listview.page.clear_primary_action();
            $('.primary-action').hide();
        }, 50);

        setTimeout(() => {
            $('.primary-action').hide();
        }, 500);
    }
};