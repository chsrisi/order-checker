import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';
import '../models.dart';

class OrdersView extends StatefulWidget {
  const OrdersView({super.key});

  @override
  State<OrdersView> createState() => _OrdersViewState();
}

class _OrdersViewState extends State<OrdersView> {
  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Column(
        children: [
          const TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: [
              Tab(text: 'Ongoing'),
              Tab(text: 'History'),
            ],
            labelColor: Colors.red,
            unselectedLabelColor: Colors.grey,
            indicatorColor: Colors.red,
          ),
          Expanded(
            child: TabBarView(
              children: [const _OngoingOrdersTab(), const _HistoryOrdersTab()],
            ),
          ),
        ],
      ),
    );
  }
}

class _OngoingOrdersTab extends StatefulWidget {
  const _OngoingOrdersTab();
  @override
  State<_OngoingOrdersTab> createState() => _OngoingOrdersTabState();
}

class _OngoingOrdersTabState extends State<_OngoingOrdersTab> {
  String? _adminHistoryFilterTag;
  final Set<int> _selectedItemIds = {};

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);
    final orders = appState.orders;
    final outboundItems = appState.outboundItems;

    return Row(
      children: [
        Expanded(
          flex: 5,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(8.0),
                child: Row(
                  children: [
                    const Text(
                      "Ongoing Orders",
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                    const Spacer(),
                    OutlinedButton.icon(
                      onPressed: appState.isLoading
                          ? null
                          : () => appState.resetShopeeCacheState(),
                      icon: const Icon(Icons.refresh, size: 18),
                      label: const Text("Reset State"),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: Colors.orange,
                        side: const BorderSide(color: Colors.orange),
                      ),
                    ),
                    const SizedBox(width: 8),
                    ElevatedButton.icon(
                      onPressed: appState.isLoading
                          ? null
                          : () => appState.fetchShopeeOrders(),
                      icon: const Icon(Icons.sync),
                      label: const Text("Sync Shopee"),
                    ),
                  ],
                ),
              ),
              Expanded(child: _buildOrdersList(context, appState, orders)),
            ],
          ),
        ),
        const VerticalDivider(width: 1, thickness: 1),
        Expanded(
          flex: 5,
          child: _buildScansView(context, appState, outboundItems),
        ),
      ],
    );
  }

  Widget _buildOrdersList(
    BuildContext context,
    AppState appState,
    List<ShopeeOrder> orders,
  ) {
    if (appState.isLoading && orders.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (orders.isEmpty) {
      return const Center(child: Text("No ongoing orders found"));
    }

    return RefreshIndicator(
      onRefresh: appState.fetchAdminLabels,
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: orders.length,
        itemBuilder: (context, index) {
          final order = orders[index];
          final requirements = order.itemList;
          final pickItemEntries = appState.pickItemEntries
              .where((e) => e.orderSn == order.orderSn)
              .toList();
          final skuMap = Map.fromEntries(
            {
              ...requirements.map(
                (e) => (e.itemSku != '' ? e.itemSku : e.modelSku) ?? 'unknown',
              ),
              ...pickItemEntries.map((e) => e.sku),
            }.map((sku) {
              final requiredQty =
                  requirements
                      .where(
                        (e) =>
                            ((e.itemSku != '' ? e.itemSku : e.modelSku) ??
                                'unknown') ==
                            sku,
                      )
                      .map((e) => e.modelQuantityPurchased)
                      .firstOrNull ??
                  0;
              final scannedQty = pickItemEntries
                  .where((e) => e.sku == sku)
                  .fold(0, (sum, e) => sum + e.qty);
              return MapEntry(sku, (requiredQty, scannedQty));
            }),
          );
          final progress = skuMap.values.fold(0, (sum, e) {
            final (requiredQty, scannedQty) = e;
            if (requiredQty == scannedQty) return sum + 1;
            return sum;
          });
          Color? textColor;
          if (skuMap.values.any((pair) {
            final (req, scan) = pair;
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

          final isUnassigned = order.ownerUser == null;

          final pickupCode = order.info
              .firstWhere(
                (i) => i.pickupCode != null && i.pickupCode!.isNotEmpty,
                orElse: () => ShopeeOrderInfo(id: 0),
              )
              .pickupCode;

          final orderSnClean = order.orderSn.trim().toLowerCase();
          final trackingNumbers = order.info
              .map((i) => i.trackingNumber?.trim().toLowerCase())
              .whereType<String>()
              .toSet();

          final hasOutboundMatch = appState.outboundItems.any((item) {
            final contentClean = item.content.trim().toLowerCase();
            return contentClean == orderSnClean ||
                trackingNumbers.contains(contentClean);
          });

          return Card(
            color: isUnassigned ? Colors.grey.shade300 : null,
            margin: const EdgeInsets.only(bottom: 12),
            child: ExpansionTile(
              shape: Border.all(color: Colors.transparent),
              collapsedShape: Border.all(color: Colors.transparent),
              leading: Icon(
                Icons.pending_actions,
                color: isUnassigned ? Colors.grey : Colors.orange,
              ),
              title: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    order.orderSn,
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      color: isUnassigned ? Colors.grey.shade700 : null,
                      decoration: hasOutboundMatch
                          ? TextDecoration.lineThrough
                          : null,
                    ),
                  ),
                  if (pickupCode != null && pickupCode.isNotEmpty)
                    Text(
                      pickupCode,
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        color: isUnassigned
                            ? Colors.grey.shade600
                            : Colors.red.shade900,
                        decoration: hasOutboundMatch
                            ? TextDecoration.lineThrough
                            : null,
                      ),
                    ),
                ],
              ),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        "User ID: ${order.ownerUser ?? 'Unassigned'} | Progress: ",
                        style: TextStyle(
                          decoration: hasOutboundMatch
                              ? TextDecoration.lineThrough
                              : null,
                        ),
                      ),
                      Text(
                        "$progress/${requirements.length} SKUs",
                        style: TextStyle(
                          color: textColor,
                          fontWeight: FontWeight.bold,
                          decoration: hasOutboundMatch
                              ? TextDecoration.lineThrough
                              : null,
                        ),
                      ),
                    ],
                  ),
                  if (order.recipientAddress != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      "Recipient: ${order.recipientAddress!.name ?? 'N/A'} (${order.recipientAddress!.city ?? 'N/A'})",
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.grey,
                        decoration: hasOutboundMatch
                            ? TextDecoration.lineThrough
                            : null,
                      ),
                    ),
                  ],
                ],
              ),
              children: [
                ...skuMap.entries.map((entry) {
                  final sku = entry.key;
                  final (requiredQty, scannedQty) = entry.value;

                  Color? textColor;
                  if (scannedQty == 0) {
                    textColor = Colors.grey;
                  } else if (scannedQty < requiredQty) {
                    textColor = Colors.orange;
                  } else if (scannedQty == requiredQty) {
                    textColor = Colors.green;
                  } else {
                    textColor = Colors.red;
                  }

                  final isSkuEmpty = sku.trim().isEmpty || sku == 'unknown';
                  final matchingItem = requirements.firstWhere(
                    (item) => (isSkuEmpty
                        ? (item.itemSku == 'unknown' || item.itemSku.isEmpty)
                        : (item.modelSku == sku || item.itemSku == sku)),
                    orElse: () => ShopeeOrderItem(
                      id: 0,
                      itemId: 0,
                      itemName: '',
                      itemSku: '',
                      modelQuantityPurchased: 0,
                      imageUrl: '',
                    ),
                  );

                  final scanMatch = pickItemEntries.where(
                    (e) => e.sku == sku && e.itemName != null && e.itemName!.isNotEmpty,
                  ).firstOrNull;

                  String displayName = matchingItem.itemName.isNotEmpty
                      ? matchingItem.itemName
                      : (scanMatch?.itemName ?? 'Unknown Item');

                  final skuPart = isSkuEmpty ? "No SKU" : sku;
                  final displaySubtext =
                      (matchingItem.modelName != null &&
                          matchingItem.modelName!.isNotEmpty)
                      ? "(${matchingItem.modelName}) $skuPart"
                      : skuPart;

                  return ListTile(
                    title: Text(displayName),
                    subtitle: Text(displaySubtext),
                    trailing: Text(
                      "$scannedQty / $requiredQty",
                      style: TextStyle(
                        color: textColor,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  );
                }),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildScansView(
    BuildContext context,
    AppState appState,
    List<OutboundItem> outboundItems,
  ) {
    final filteredItems = _adminHistoryFilterTag == null
        ? outboundItems
        : outboundItems
              .where((item) => item.tags.contains(_adminHistoryFilterTag))
              .toList();

    final allTags = outboundItems
        .expand((e) => e.tags)
        .toSet()
        .toList();
    allTags.sort();

    return Column(
      children: [
        // Column 1: Filters and List
        Expanded(
          child: Column(
            children: [
              // Filters
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8.0),
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 16.0),
                  child: Row(
                    children: [
                      ChoiceChip(
                        label: const Text("All"),
                        selected: _adminHistoryFilterTag == null,
                        onSelected: (selected) {
                          if (selected) {
                            setState(() => _adminHistoryFilterTag = null);
                          }
                        },
                      ),
                      const SizedBox(width: 8),
                      ...allTags.map((tag) {
                        return Padding(
                          padding: const EdgeInsets.only(right: 8.0),
                          child: ChoiceChip(
                            label: Text(tag),
                            selected: _adminHistoryFilterTag == tag,
                            onSelected: (selected) {
                              setState(() {
                                _adminHistoryFilterTag = selected ? tag : null;
                              });
                            },
                          ),
                        );
                      }),
                    ],
                  ),
                ),
              ),
              Expanded(
                child: RefreshIndicator(
                  onRefresh: appState.fetchHistory,
                  child: ListView.builder(
                    itemCount: filteredItems.length,
                    itemBuilder: (context, index) {
                      final item = filteredItems[index];
                      final DateTime date = item.createdAt.toLocal();
                      final bool isSelected = _selectedItemIds.contains(
                        item.id,
                      );

                      return Card(
                        margin: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 4,
                        ),
                        child: ListTile(
                          leading: Checkbox(
                            value: isSelected,
                            onChanged: (val) {
                              setState(() {
                                if (val == true) {
                                  _selectedItemIds.add(item.id);
                                } else {
                                  _selectedItemIds.remove(item.id);
                                }
                              });
                            },
                          ),
                          title: Row(
                            children: [
                              Expanded(
                                child: Text(
                                  item.content,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                              Wrap(
                                spacing: 4,
                                children: item.tags.map((tag) => Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 8,
                                    vertical: 2,
                                  ),
                                  decoration: BoxDecoration(
                                    color: Colors.red.shade100,
                                    borderRadius: BorderRadius.circular(12),
                                  ),
                                  child: Text(
                                    tag,
                                    style: TextStyle(
                                      fontSize: 10,
                                      color: Colors.red.shade900,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                )).toList(),
                              ),
                            ],
                          ),
                          subtitle: Text(
                            "By: ${item.ownerUser ?? 'Unknown'}\nScan time: ${date.hour}:${date.minute.toString().padLeft(2, '0')} - ${date.day}/${date.month}",
                          ),
                          trailing: IconButton(
                            icon: const Icon(
                              Icons.delete_outline,
                              color: Colors.red,
                            ),
                            onPressed: () => _deleteEntry(appState, item.id),
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ),
            ],
          ),
        ),
        // Bottom Control Bar
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.05),
                blurRadius: 10,
                offset: const Offset(0, -5),
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  RichText(
                    text: TextSpan(
                      style: const TextStyle(
                        fontSize: 12,
                        color: Colors.grey,
                        fontWeight: FontWeight.w500,
                      ),
                      children: [
                        TextSpan(
                          text:
                              "Previous close: ${appState.lastCloseOutbound} out",
                        ),
                        if (appState.lastCloseOrdersDone > 0)
                          TextSpan(
                            text: ", ${appState.lastCloseOrdersDone} done",
                            style: const TextStyle(color: Colors.green),
                          ),
                      ],
                    ),
                  ),
                  if (appState.lastCloseUnknown > 0) ...[
                    const Text(
                      " - ",
                      style: TextStyle(fontSize: 12, color: Colors.grey),
                    ),
                    Text(
                      "Unknown ${appState.lastCloseUnknown}",
                      style: const TextStyle(
                        fontSize: 12,
                        color: Colors.red,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => _exportScans(appState),
                      icon: const Icon(Icons.download, size: 18),
                      label: const Text("Export CSV"),
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: () => _closePeriod(appState),
                      icon: const Icon(Icons.check_circle_outline, size: 18),
                      label: Text(
                        _selectedItemIds.isEmpty
                            ? "Close Period (All)"
                            : "Close Period (${_selectedItemIds.length})",
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.red,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                    ),
                  ),
                ],
              ),
              if (_selectedItemIds.isNotEmpty) ...[
                const SizedBox(height: 8),
                TextButton.icon(
                  onPressed: () => _deleteSelectedItems(appState),
                  icon: const Icon(Icons.delete_outline, size: 16),
                  label: Text("Delete Selected ${_selectedItemIds.length}"),
                  style: TextButton.styleFrom(foregroundColor: Colors.red),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Future<void> _deleteEntry(AppState appState, int id) async {
    final success = await appState.deleteEntry(id);
    if (!mounted) return;
    if (success) {
      setState(() => _selectedItemIds.remove(id));
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Entry deleted successfully')),
      );
    }
  }

  Future<void> _deleteSelectedItems(AppState appState) async {
    final bool? confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text("Delete Selected"),
        content: Text(
          "Are you sure you want to delete ${_selectedItemIds.length} items?",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text("Delete"),
          ),
        ],
      ),
    );
    if (confirm != true) return;
    final success = await appState.deleteSelectedItems(
      _selectedItemIds.toList(),
    );
    if (!mounted) return;
    if (success) {
      setState(() => _selectedItemIds.clear());
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Selected items deleted')));
    }
  }

  Future<void> _exportScans(AppState appState) async {
    final success = await appState.exportScans();
    if (!mounted) return;
    if (!success) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Export failed or not supported on this platform'),
        ),
      );
    }
  }

  Future<void> _closePeriod(AppState appState) async {
    final List<OutboundItem> itemsToClose = _selectedItemIds.isEmpty
        ? appState.outboundItems
        : appState.outboundItems
              .where((i) => _selectedItemIds.contains(i.id))
              .toList();

    if (itemsToClose.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text("No items to close")));
      return;
    }

    final bool? confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text("Close Period"),
        content: Text(
          "Are you sure you want to close this period for ${itemsToClose.length} items? Matching Shopee orders will be marked as done.",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text("Close Period"),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    final contents = itemsToClose.map((i) => i.content).toList();
    final success = await appState.closePeriod(contents);

    if (!mounted) return;
    if (success) {
      setState(() => _selectedItemIds.clear());
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Period closed successfully")),
      );
    }
  }
}

sealed class _OrderItemT {}

class _OrderT extends _OrderItemT {
  final ShopeeOrder order;
  _OrderT(this.order);
}

class _OutboundItemT extends _OrderItemT {
  final OutboundItem outboundItem;
  _OutboundItemT(this.outboundItem);
}

class _HistoryOrdersTab extends StatefulWidget {
  const _HistoryOrdersTab();
  @override
  State<_HistoryOrdersTab> createState() => _HistoryOrdersTabState();
}

class _HistoryOrdersTabState extends State<_HistoryOrdersTab> {
  String _mode = 'inbound'; // 'inbound' or 'outbound'
  DateTime? _fromDate;
  DateTime? _toDate;
  final TextEditingController _searchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _fromDate = DateTime.now().subtract(const Duration(days: 1));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      Provider.of<AppState>(context, listen: false).fetchAdminHistory();
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _applyPreviousClose(AppState appState) {
    if (appState.historyOutboundItems.isEmpty) return;
    final lastItem = appState.historyOutboundItems.first;
    setState(() {
      _mode = 'outbound';
      _searchController.text = lastItem.tags.firstOrNull ?? '';
      _fromDate = null;
      _toDate = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);

    List<_OrderItemT> items = _mode == 'inbound'
        ? appState.historyOrders.map((e) => _OrderT(e)).toList()
        : appState.historyOutboundItems.map((e) => _OutboundItemT(e)).toList();

    // filter closed orders
    items = items.where((item) {
      return switch (item) {
        _OrderT(order: final o) => o.done == true,
        _OutboundItemT(outboundItem: final o) => o.closed == true,
      };
    }).toList();

    if (_fromDate != null) {
      items = items.where((item) {
        final DateTime dt = switch (item) {
          _OrderT(order: final o) => o.shipBy.toLocal(),
          _OutboundItemT(outboundItem: final o) => o.closedAt!.toLocal(),
        };
        final startOfDay = DateTime(
          _fromDate!.year,
          _fromDate!.month,
          _fromDate!.day,
        );
        return dt.isAfter(startOfDay) || dt.isAtSameMomentAs(startOfDay);
      }).toList();
    }
    if (_toDate != null) {
      items = items.where((item) {
        final DateTime dt = switch (item) {
          _OrderT(order: final o) => o.doneAt!.toLocal(),
          _OutboundItemT(outboundItem: final o) => o.closedAt!.toLocal(),
        };
        final endOfDay = DateTime(
          _toDate!.year,
          _toDate!.month,
          _toDate!.day,
          23,
          59,
          59,
        );
        return dt.isBefore(endOfDay) || dt.isAtSameMomentAs(endOfDay);
      }).toList();
    }

    final query = _searchController.text.toLowerCase().trim();
    if (query.isNotEmpty) {
      items = items.where((item) {
        return switch (item) {
          _OrderT(order: final o) =>
            o.orderSn.toLowerCase().contains(query) ||
                (o.ownerUser?.toLowerCase().contains(query) ?? false),
          _OutboundItemT(outboundItem: final o) =>
            o.content.toLowerCase().contains(query) ||
                o.tags.any((tag) => tag.toLowerCase().contains(query)) ||
                (o.ownerUser?.toLowerCase().contains(query) ?? false),
        };
      }).toList();
    }

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(8.0),
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              ToggleButtons(
                isSelected: [_mode == 'inbound', _mode == 'outbound'],
                onPressed: (index) {
                  setState(() {
                    _mode = index == 0 ? 'inbound' : 'outbound';
                  });
                },
                borderRadius: BorderRadius.circular(12),
                children: const [
                  Padding(
                    padding: EdgeInsets.symmetric(horizontal: 12),
                    child: Text("Inbound"),
                  ),
                  Padding(
                    padding: EdgeInsets.symmetric(horizontal: 12),
                    child: Text("Outbound"),
                  ),
                ],
              ),
              OutlinedButton.icon(
                icon: const Icon(Icons.date_range, size: 16),
                label: Text(
                  _fromDate == null
                      ? "From: Any"
                      : "From: ${_fromDate!.year}-${_fromDate!.month}-${_fromDate!.day}",
                ),
                onPressed: () async {
                  final date = await showDatePicker(
                    context: context,
                    initialDate: _fromDate ?? DateTime.now(),
                    firstDate: DateTime(2020),
                    lastDate: DateTime(2100),
                  );
                  if (date != null) setState(() => _fromDate = date);
                },
              ),
              OutlinedButton.icon(
                icon: const Icon(Icons.date_range, size: 16),
                label: Text(
                  _toDate == null
                      ? "To: Any"
                      : "To: ${_toDate!.year}-${_toDate!.month}-${_toDate!.day}",
                ),
                onPressed: () async {
                  final date = await showDatePicker(
                    context: context,
                    initialDate: _toDate ?? DateTime.now(),
                    firstDate: DateTime(2020),
                    lastDate: DateTime(2100),
                  );
                  if (date != null) setState(() => _toDate = date);
                },
              ),
              IconButton(
                icon: const Icon(Icons.clear),
                tooltip: "Clear Dates",
                onPressed: () => setState(() {
                  _fromDate = null;
                  _toDate = null;
                }),
              ),
              TextButton.icon(
                icon: const Icon(Icons.restore, size: 16),
                label: const Text("Show Previous Close"),
                onPressed: () => _applyPreviousClose(appState),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16.0),
          child: TextField(
            controller: _searchController,
            decoration: InputDecoration(
              hintText: "Search anything...",
              prefixIcon: const Icon(Icons.search),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
              ),
              isDense: true,
              suffixIcon: IconButton(
                icon: const Icon(Icons.clear),
                onPressed: () {
                  _searchController.clear();
                  setState(() {});
                },
              ),
            ),
            onChanged: (v) => setState(() {}),
          ),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: RefreshIndicator(
            onRefresh: appState.fetchAdminHistory,
            child: ListView.builder(
              itemCount: items.length,
              itemBuilder: (context, index) {
                final item = items[index];
                return switch (item) {
                  _OrderT(order: final o) => () {
                    final date = o.shipBy.toLocal();
                    return Card(
                      margin: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 4,
                      ),
                      child: ListTile(
                        leading: const Icon(
                          Icons.check_circle,
                          color: Colors.green,
                        ),
                        title: Text(
                          o.orderSn,
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        subtitle: Text(
                          "Username: ${o.ownerUser}\nDone: ${date.hour}:${date.minute.toString().padLeft(2, '0')} - ${date.day}/${date.month}",
                        ),
                      ),
                    );
                  }(),
                  _OutboundItemT(outboundItem: final o) => () {
                    final date = o.createdAt.toLocal();
                    return Card(
                      margin: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 4,
                      ),
                      child: ListTile(
                        leading: const Icon(Icons.outbox, color: Colors.blue),
                        title: Row(
                          children: [
                            Expanded(
                              child: Text(
                                o.content,
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                            if (o.tags.isNotEmpty)
                              Padding(
                                padding: const EdgeInsets.only(left: 8.0),
                                child: Wrap(
                                  spacing: 4,
                                  children: o.tags.map((tag) => Chip(
                                    label: Text(tag),
                                    visualDensity: VisualDensity.compact,
                                    materialTapTargetSize:
                                        MaterialTapTargetSize.shrinkWrap,
                                  )).toList(),
                                ),
                              ),
                          ],
                        ),
                        subtitle: Text(
                          "Username: ${o.ownerUser ?? 'Unknown'} | "
                          "At: ${date.hour}:${date.minute.toString().padLeft(2, '0')} - ${date.day}/${date.month}",
                        ),
                      ),
                    );
                  }(),
                };
              },
            ),
          ),
        ),
      ],
    );
  }
}
