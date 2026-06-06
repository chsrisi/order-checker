import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';
import '../models.dart';

class OrdersInputScreen extends StatefulWidget {
  final String? selectedOrder;
  const OrdersInputScreen({super.key, this.selectedOrder});

  @override
  State<OrdersInputScreen> createState() => _OrdersInputScreenState();
}

class _OrdersInputScreenState extends State<OrdersInputScreen> {
  final TextEditingController _scanController = TextEditingController();
  final TextEditingController _orderQtyController = TextEditingController(
    text: "1",
  );
  final FocusNode _scanFocusNode = FocusNode();
  String _selectedMode = 'order'; // 'order' or 'item'

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final appState = Provider.of<AppState>(context, listen: false);
      appState.onShowMessage = (message, {isError = false, isAlert = false}) {
        if (!mounted) return;
        if (isAlert) {
          showDialog(
            context: context,
            builder: (context) => AlertDialog(
              title: Text(isError ? "Error" : "Notification"),
              content: Text(message),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text("OK"),
                ),
              ],
            ),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(message),
              backgroundColor: isError ? Colors.red : null,
            ),
          );
        }
      };
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        final appState = Provider.of<AppState>(context, listen: false);
        appState.onShowMessage = null;
      }
    });
    _scanController.dispose();
    _orderQtyController.dispose();
    _scanFocusNode.dispose();
    super.dispose();
  }

  void _handleSubmit(AppState appState) {
    if (_selectedMode == 'order') {
      final orderSn = _scanController.text.trim();
      if (!RegExp(r'^\d{6}.*').hasMatch(orderSn)) {
        appState.onShowMessage?.call(
          "Invalid Order SN. Must start with YYMMDD.",
          isError: true,
          isAlert: true,
        );
        _scanFocusNode.requestFocus();
        return;
      }
      appState.acquireOrder(orderSn);
    } else {
      final sku = _scanController.text.trim();
      final qtyStr = _orderQtyController.text.trim();
      final int qty = int.tryParse(qtyStr) ?? 1;
      appState.postScanEntry(sku, qty, orderSn: widget.selectedOrder);
    }
    _scanController.clear();
    _orderQtyController.text = "1";
    _scanFocusNode.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);
    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.shopping_basket, size: 40, color: Colors.orange),
              const SizedBox(width: 16),
              const Text(
                "Orders Input",
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 16),
          ToggleButtons(
            isSelected: [_selectedMode == 'order', _selectedMode == 'item'],
            onPressed: (index) =>
                setState(() => _selectedMode = index == 0 ? 'order' : 'item'),
            borderRadius: BorderRadius.circular(8),
            children: const [
              Padding(
                padding: EdgeInsets.symmetric(horizontal: 16),
                child: Text("Order"),
              ),
              Padding(
                padding: EdgeInsets.symmetric(horizontal: 16),
                child: Text("Item"),
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (_selectedMode == 'order')
            TextField(
              controller: _scanController,
              focusNode: _scanFocusNode,
              decoration: const InputDecoration(
                hintText: "Input Order SN...",
                border: OutlineInputBorder(),
              ),
              onSubmitted: (_) => _handleSubmit(appState),
            )
          else
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: TextField(
                    controller: _scanController,
                    focusNode: _scanFocusNode,
                    decoration: const InputDecoration(
                      hintText: "SKU",
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    controller: _orderQtyController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      hintText: "Qty",
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
              ],
            ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: appState.isSaving
                  ? null
                  : () => _handleSubmit(appState),
              icon: appState.isSaving
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.qr_code_scanner),
              label: const Text("Submit Scan"),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.orange,
                foregroundColor: Colors.white,
              ),
            ),
          ),
          const SizedBox(height: 8),
          if (widget.selectedOrder != null)
            Text(
              "Active Order: ${appState.orders.firstWhere((o) => o.orderSn == widget.selectedOrder).orderSn}",
              style: const TextStyle(
                fontWeight: FontWeight.bold,
                color: Colors.grey,
              ),
            ),
        ],
      ),
    );
  }
}

class OrdersHistoryScreen extends StatefulWidget {
  final String? activeOrder;
  final Function(String?) setActiveOrder;
  const OrdersHistoryScreen({
    super.key,
    this.activeOrder,
    required this.setActiveOrder,
  });

  @override
  State<OrdersHistoryScreen> createState() => _OrdersHistoryScreenState();
}

class _OrdersHistoryScreenState extends State<OrdersHistoryScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final appState = Provider.of<AppState>(context, listen: false);
      appState.onShowMessage = (message, {isError = false, isAlert = false}) {
        if (!mounted) return;
        if (isAlert) {
          showDialog(
            context: context,
            builder: (context) => AlertDialog(
              title: Text(isError ? "Error" : "Notification"),
              content: Text(message),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text("OK"),
                ),
              ],
            ),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(message),
              backgroundColor: isError ? Colors.red : null,
            ),
          );
        }
      };
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        final appState = Provider.of<AppState>(context, listen: false);
        appState.onShowMessage = null;
      }
    });
    super.dispose();
  }

  void _showUnassignDialog(
    BuildContext context,
    AppState appState,
    String orderSn,
    String sku,
    int currentQty,
    int requiredQty,
  ) {
    int defaultQty = currentQty > requiredQty
        ? currentQty - requiredQty
        : currentQty;
    final qtyController = TextEditingController(text: defaultQty.toString());

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text("Unassign SKU: $sku"),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text("Move to Unknown? (Max: $currentQty)"),
            TextField(
              controller: qtyController,
              keyboardType: TextInputType.number,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("Cancel"),
          ),
          ElevatedButton(
            onPressed: () {
              final qty = int.tryParse(qtyController.text) ?? 0;
              if (qty > 0 && qty <= currentQty) {
                appState.unassignSku(orderSn, sku, qty);
                Navigator.pop(context);
              }
            },
            child: const Text("Move"),
          ),
        ],
      ),
    );
  }

  void _showAssignDialog(
    BuildContext context,
    AppState appState,
    PickItemEntry entry,
  ) {
    ShopeeOrder? selectedOrder;
    final qtyController = TextEditingController(text: entry.qty.toString());

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text("Assign to Label"),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            DropdownMenu<ShopeeOrder>(
              width: 250,
              enableFilter: true,
              label: const Text("Select Order"),
              onSelected: (order) => selectedOrder = order,
              dropdownMenuEntries: appState.orders
                  .where((o) => o.done != true)
                  .map((o) => DropdownMenuEntry(value: o, label: o.orderSn))
                  .toList(),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: qtyController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: "Quantity",
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("Cancel"),
          ),
          ElevatedButton(
            onPressed: () {
              if (selectedOrder != null) {
                final qty = int.tryParse(qtyController.text);
                final matchingItem = selectedOrder!.itemList
                    .where((i) => i.modelSku == entry.sku)
                    .firstOrNull;
                appState.assignToLabel(
                  entry.id,
                  selectedOrder!.orderSn,
                  qty: qty,
                  orderItemQty: matchingItem?.modelQuantityPurchased ?? 0,
                );
                Navigator.pop(context);
              } else {
                appState.onShowMessage?.call(
                  "Please select a label.",
                  isError: true,
                );
              }
            },
            child: const Text("Assign"),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);

    return Column(
      children: [
        Expanded(
          child: RadioGroup<String>(
            groupValue: widget.activeOrder,
            onChanged: widget.setActiveOrder,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const Text(
                  "Labels",
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: Colors.grey,
                  ),
                ),
                ...appState.orders.where((o) => o.done != true).map((order) {
                  final requirements = order.itemList;
                  final scanned = appState.pickItemEntries.where(
                    (e) => e.orderSn == order.orderSn,
                  );
                  final skuMap = Map.fromEntries(
                    {
                      ...requirements.map((e) => e.modelSku ?? e.itemSku),
                      ...scanned.map((e) => e.sku),
                    }.map((sku) {
                      final reqQty = requirements
                          .firstWhere((e) => (e.modelSku ?? e.itemSku) == sku)
                          .modelQuantityPurchased;
                      final scanQty = scanned
                          .where((e) => e.sku == sku)
                          .fold(0, (sum, e) => sum + e.qty);
                      return MapEntry(sku, (reqQty, scanQty));
                    }),
                  );
                  final progress = skuMap.values.fold(0, (sum, e) {
                    var (req, scan) = e;
                    if (req == scan) return sum + 1;
                    return sum;
                  });
                  Color? textColor;
                  if (skuMap.values.any((pair) {
                    var (req, scan) = pair;
                    return req == 0;
                  })) {
                    textColor = Colors.red;
                  } else if (progress == 0) {
                    textColor = Colors.grey;
                  } else if (progress < requirements.length) {
                    textColor = Colors.orange;
                  } else {
                    textColor = Colors.green;
                  }
                  return Card(
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Padding(
                          padding: const EdgeInsets.only(left: 8.0, top: 16.0),
                          child: Radio<String>(
                            toggleable: true,
                            value: order.orderSn,
                          ),
                        ),
                        Expanded(
                          child: ExpansionTile(
                            shape: Border.all(color: Colors.transparent),
                            collapsedShape: Border.all(
                              color: Colors.transparent,
                            ),
                            title: Text(
                              order.orderSn,
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            subtitle: Row(
                              children: [
                                const Text("Progress: "),
                                Text(
                                  "$progress/${requirements.length} SKUs",
                                  style: TextStyle(
                                    fontWeight: FontWeight.bold,
                                    color: textColor,
                                  ),
                                ),
                              ],
                            ),
                            onExpansionChanged: (expanded) {
                              if (expanded) {
                                widget.setActiveOrder(order.orderSn);
                              } else {
                                widget.setActiveOrder(null);
                              }
                            },
                            children: skuMap.entries.map((entry) {
                              final sku = entry.key;
                              final (reqQty, scanQty) = entry.value;

                              Color? textColor;
                              if (scanQty == 0) {
                                textColor = Colors.grey;
                              } else if (scanQty < reqQty) {
                                textColor = Colors.orange;
                              } else if (scanQty == reqQty) {
                                textColor = Colors.green;
                              } else {
                                textColor = Colors.red;
                              }

                              return ListTile(
                                title: Text(sku),
                                trailing: Text(
                                  "$scanQty / $reqQty",
                                  style: TextStyle(
                                    color: textColor,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                                onLongPress: () => _showUnassignDialog(
                                  context,
                                  appState,
                                  order.orderSn,
                                  sku,
                                  scanQty,
                                  reqQty,
                                ),
                              );
                            }).toList(),
                          ),
                        ),
                      ],
                    ),
                  );
                }),
                const SizedBox(height: 16),
                const Text(
                  "Unknown / Split Scans",
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: Colors.grey,
                  ),
                ),
                ...appState.pickItemEntries
                    .where((e) => e.orderSn == null && e.qty > 0)
                    .map((entry) {
                      return Card(
                        color: Colors.red.shade50,
                        child: ListTile(
                          leading: const Icon(
                            Icons.help_outline,
                            color: Colors.red,
                          ),
                          title: Text(entry.sku),
                          subtitle: Text("Qty: ${entry.qty}"),
                          trailing: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                icon: const Icon(
                                  Icons.add_task,
                                  color: Colors.blue,
                                ),
                                onPressed: () =>
                                    _showAssignDialog(context, appState, entry),
                              ),
                              IconButton(
                                icon: const Icon(
                                  Icons.delete_outline,
                                  color: Colors.red,
                                ),
                                onPressed: () =>
                                    appState.deleteScanEntry(entry.id),
                              ),
                            ],
                          ),
                        ),
                      );
                    }),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class OrdersView extends StatefulWidget {
  final int subIndex;
  const OrdersView({super.key, required this.subIndex});

  @override
  State<OrdersView> createState() => _OrdersViewState();
}

class _OrdersViewState extends State<OrdersView> {
  String? _activeOrder;

  void setActiveOrder(String? order) {
    setState(() {
      _activeOrder = order;
    });
  }

  @override
  Widget build(BuildContext context) {
    switch (widget.subIndex) {
      case 0:
        return OrdersInputScreen(selectedOrder: _activeOrder);
      case 1:
        return OrdersHistoryScreen(
          activeOrder: _activeOrder,
          setActiveOrder: setActiveOrder,
        );
      default:
        return const Center(child: Text("Page not found"));
    }
  }
}
