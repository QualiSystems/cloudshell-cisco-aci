import acitoolkit.acitoolkit as aci

INTERFACE_TYPE = "eth"
L2_INTERFACE_ENCAP_TYPE = "vlan"

PORT_TRUNK_MODE = "regular"
PORT_ACCESS_UNTAGGED_MODE = "untagged"
PORT_ACCESS_MODE = "native"
PORT_MODE_MAP = {
    "access": PORT_ACCESS_MODE,  # todo: clarify which option use for the access mode (802.1P|Untagged)
    "trunk": PORT_TRUNK_MODE
}


class FixedFexInterface(aci.FexInterface):
    @staticmethod
    def is_interface():
        """Override this method to fix acitoolkit bug

        Without this FEX Interface data will not be added to the HTTP payload"""
        return True


class CiscoACIControllerHTTPClient(object):
    def __init__(self, logger, address, user=None, password=None, scheme="https", port=443):
        """

        :param logging.Logger logger:
        :param str address: controller IP address
        :param str user: controller username
        :param str password: controller password
        :param str scheme: protocol (http|https)
        :param int port: controller port
        """
        full_url = "{}://{}:{}".format(scheme.lower(), address, port)
        self._logger = logger
        self._session = aci.Session(url=full_url, uid=user, pwd=password)
        self._login()

    def _login(self):
        """

        :return:
        """
        resp = self._session.login()

        if not resp.ok:
            self._logger.error("Unable to login to the ACI Controller. HTTP Status code: {} Response: {}"
                               .format(resp.status_code, resp.content))
            raise Exception("Unable to login to the ACI Controller")

    def get_tenant(self, tenant_name):
        """

        :param tenant_name:
        :return:
        """
        for tenant in aci.Tenant.get(session=self._session):
            if tenant_name == tenant.name:
                return tenant

        raise Exception("Unable to find Tenant with name '{}'".format(tenant_name))

    def get_app_profile(self, app_profile_name, tenant=None):
        """

        :param app_profile_name:
        :param tenant:
        :return:
        """
        for app_profile in aci.AppProfile.get(session=self._session, tenant=tenant):
            if app_profile_name == app_profile.name:
                return app_profile

        raise Exception("Unable to find Application Profile with name '{}'".format(app_profile))

    def get_epg(self, epg_name, tenant=None):
        """

        :param epg_name:
        :param tenant:
        :return:
        """
        for epg in aci.EPG.get(session=self._session, tenant=tenant):
            if epg_name == epg.name:
                return epg

        raise Exception("Unable to find EPG with name '{}'".format(epg_name))

    def get_bd(self, bd_name, tenant=None):
        """

        :param bd_name:
        :param tenant:
        :return:
        """
        for bd in aci.BridgeDomain.get(session=self._session, tenant=tenant):
            if bd_name == bd.name:
                return bd

        raise Exception("Unable to find Bridge Domain with name '{}'".format(bd_name))

    def get_leaf_ports(self):
        """Get leaf ports in the next format: pod->node-><fex>->slot->port

        :return:
        """
        ports_data = {"pods": {}}
        interfaces = aci.Interface.get(session=self._session)

        for interface in interfaces:
            if interface.porttype.lower() == "leaf":
                pod_data = ports_data["pods"].setdefault(interface.pod, {"nodes": {}})
                node_data = pod_data["nodes"].setdefault(interface.node, {"slots": {}, "fexs": {}})
                slot_data = node_data["slots"].setdefault(interface.module, {"ports": []})
                slot_data["ports"].append({
                    "id": interface.port,
                    "name": interface.name
                })
            elif interface.porttype == "extchhp":  # FEX ports
                pod_data = ports_data["pods"].setdefault(interface.pod, {"nodes": {}})
                node_data = pod_data["nodes"].setdefault(interface.node, {"slots": {}, "fexs": {}})
                fex_data = node_data["fexs"].setdefault(interface.node, {"slots": {}})
                slot_data = fex_data["slots"].setdefault(interface.module, {"ports": []})
                slot_data["ports"].append({
                    "id": interface.port,
                    "name": interface.name
                })

        return ports_data

    def add_port_to_epg(self, pod, node, fex, module, port, vlan_id, port_mode, tenant_name, app_profile_name,
                        epg_name):
        """

        :param pod:
        :param node:
        :param fex:
        :param module:
        :param port:
        :param vlan_id:
        :param port_mode:
        :param tenant_name:
        :param app_profile_name:
        :param epg_name:
        :return:
        """
        tenant = self.get_tenant(tenant_name)

        app = aci.AppProfile(app_profile_name, tenant)
        epg = aci.EPG(epg_name=epg_name, parent=app)

        # create the physical interface object
        if fex is None:
            intf = aci.Interface(interface_type=INTERFACE_TYPE,
                                 pod=pod,
                                 node=node,
                                 module=module,
                                 port=port)
        else:
            intf = FixedFexInterface(if_type=INTERFACE_TYPE,
                                     pod=pod,
                                     node=node,
                                     fex=fex,
                                     module=module,
                                     port=port)

        # create a VLAN interface and attach to the physical interface
        vlan_intf = aci.L2Interface(name=vlan_id,
                                    encap_type=L2_INTERFACE_ENCAP_TYPE,
                                    encap_id=vlan_id,
                                    encap_mode=PORT_MODE_MAP[port_mode])

        vlan_intf.attach(intf)

        # attach EPG to the VLAN interface
        epg.attach(vlan_intf)

        # push the tenant config to the APIC
        resp = tenant.push_to_apic(self._session)
        self._logger.info("Pushed Tenant data {}".format(tenant.get_json()))

        if not resp.ok:
            raise Exception('Could not push tenant configuration to APIC. Error response: {}'.format(resp.content))

    def remove_port_from_epg(self, pod, node, fex, module, port, vlan_id, port_mode, tenant_name,
                             app_profile_name, epg_name):
        """

        :param pod:
        :param node:
        :param fex:
        :param module:
        :param port:
        :param vlan_id:
        :param port_mode:
        :param tenant_name:
        :param app_profile_name:
        :param epg_name:
        :return:
        """
        tenant = self.get_tenant(tenant_name)

        app = aci.AppProfile(app_profile_name, tenant)
        epg = aci.EPG(epg_name=epg_name, parent=app)

        # create the physical interface object
        if fex is None:
            intf = aci.Interface(interface_type=INTERFACE_TYPE,
                                 pod=pod,
                                 node=node,
                                 module=module,
                                 port=port)
        else:
            intf = FixedFexInterface(if_type=INTERFACE_TYPE,
                                     pod=pod,
                                     node=node,
                                     fex=fex,
                                     module=module,
                                     port=port)

        # create a VLAN interface and attach to the physical interface
        vlan_intf = aci.L2Interface(name=vlan_id,
                                    encap_type=L2_INTERFACE_ENCAP_TYPE,
                                    encap_id=vlan_id,
                                    encap_mode=PORT_MODE_MAP[port_mode])

        vlan_intf.attach(intf)

        # attach EPG to the VLAN interface
        epg.detach(vlan_intf)

        # push the tenant config to the APIC
        resp = tenant.push_to_apic(self._session)
        self._logger.info("Pushed Tenant data {}".format(tenant.get_json()))

        if not resp.ok:
            raise Exception('Could not push tenant configuration to APIC. Error response: {}'.format(resp.content))

    def get_tenants_structure(self):
        """Get all Tenants structure in the next format:

        [{"name": "tenant_1", "app_profiles": [{"name": "app_profile_1", "epgs": [{"name": "EPG_1"}]}]}]
        :rtype: list[dict]
        """
        tenants_structure = []
        tenants = aci.Tenant.get_deep(self._session)
        self._logger.info("Tenants info from the APIC: {}".format(tenants))

        for tenant in tenants:
            app_profiles = []
            tenants_structure.append({
                "name": tenant.name,
                "app_profiles": app_profiles
            })
            for tenant_child in tenant.get_children():
                if isinstance(tenant_child, aci.AppProfile):
                    epgs = []
                    app_profiles.append({
                        "name": tenant_child.name,
                        "epgs": epgs
                    })

                    for app_profile_child in tenant_child.get_children():
                        if isinstance(app_profile_child, aci.CommonEPG):
                            epgs.append({
                                "name": app_profile_child.name
                            })

        self._logger.info("Parsed Tenants structure: {}".format(tenants_structure))
        return tenants_structure

    def create_aci_resources(self, tenant_name, app_profile_name, epg_name, bd_name, bd_ip_address=None, bd_mask=None):
        """

        :param tenant_name:
        :param app_profile_name:
        :param epg_name:
        :param bd_name:
        :param bd_ip_address:
        :param bd_mask:
        :return:
        """
        tenant = self.get_tenant(tenant_name)

        app = aci.AppProfile(name=app_profile_name, parent=tenant)
        epg = aci.EPG(epg_name=epg_name, parent=app)

        bd = aci.BridgeDomain(bd_name=bd_name, parent=tenant)
        epg.add_bd(bd)

        bd.set_arp_flood('yes')
        bd.set_unicast_route('yes')

        if bd_ip_address:
            bd.set_unicast_route('yes')
            subnet = aci.Subnet('', bd)
            subnet.addr = "{}/{}".format(bd_ip_address, bd_mask)
            subnet.set_scope("private")
        else:
            bd.set_unicast_route('no')

        resp = tenant.push_to_apic(self._session)
        self._logger.info("Pushed Tenant data {}".format(tenant.get_json()))

        if not resp.ok:
            raise Exception('Could not push tenant configuration to APIC. Error response: {}'.format(resp.content))

    def remove_app_profile(self, tenant_name, app_profile_name):
        """

        :param tenant_name:
        :param app_profile_name:
        :return:
        """
        tenant = self.get_tenant(tenant_name)
        app_profile = self.get_app_profile(app_profile_name=app_profile_name, tenant=tenant)

        app_profile.mark_as_deleted()

        resp = tenant.push_to_apic(self._session)
        self._logger.info("Pushed Tenant data {}".format(tenant.get_json()))

        if not resp.ok:
            raise Exception('Could not push tenant configuration to APIC. Error response: {}'.format(resp.content))

    def remove_bridge_domain(self, tenant_name, bd_name):
        """

        :param tenant_name:
        :param bd_name:
        :return:
        """
        tenant = self.get_tenant(tenant_name)
        bd = self.get_bd(bd_name=bd_name, tenant=tenant)

        bd.mark_as_deleted()

        resp = tenant.push_to_apic(self._session)
        self._logger.info("Pushed Tenant data {}".format(tenant.get_json()))

        if not resp.ok:
            raise Exception('Could not push tenant configuration to APIC. Error response: {}'.format(resp.content))
